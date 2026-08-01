"""Application entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from quest_renamer import __version__
from quest_renamer.infrastructure.activity_log import ActivityLog
from quest_renamer.infrastructure.adb_device import AdbDeviceService
from quest_renamer.infrastructure.adb_installer import AdbApkInstaller
from quest_renamer.infrastructure.apk_analyzer import ApktoolAnalyzer
from quest_renamer.infrastructure.apk_build_engine import StagedApkBuildEngine
from quest_renamer.infrastructure.app_paths import platform_app_paths
from quest_renamer.infrastructure.detailed_apk_inspector import FullDecodeApkInspector
from quest_renamer.infrastructure.github_releases import (
    GitHubReleaseChecker,
    load_update_channel,
)
from quest_renamer.infrastructure.legacy_identity import (
    MIGRATION_ERROR_NAME,
    LegacyIdentityMigrationError,
    migrate_legacy_signing_identity,
)
from quest_renamer.infrastructure.local_bundles import LocalBundleInspector
from quest_renamer.infrastructure.older_firmware_patch import verified_older_firmware_asset
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.infrastructure.signing_backup import SigningIdentityManager
from quest_renamer.infrastructure.tool_manager import PinnedToolManager
from quest_renamer.infrastructure.toolchain import (
    Toolchain,
    load_tool_catalog,
    resolve_toolchain,
)
from quest_renamer.infrastructure.trash import move_to_trash
from quest_renamer.presentation.app_controller import AppController
from quest_renamer.presentation.bulk_controller import BulkController
from quest_renamer.presentation.file_dialog_controller import FileDialogController
from quest_renamer.presentation.inspector_controller import InspectorController
from quest_renamer.presentation.tool_controller import ToolController
from quest_renamer.presentation.update_controller import UpdateController
from quest_renamer.services.preflight import AutomaticPreflight


def initial_folder(arguments: list[str]) -> Path | None:
    """Return the first existing folder passed by a launcher or file association."""
    for value in arguments:
        if value.startswith("-"):
            continue
        candidate = Path(value).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return None


def package_resource_root(
    *,
    module_file: Path | None = None,
    frozen_root: Path | None = None,
) -> Path:
    """Resolve package data in source installs and PyInstaller onedir bundles."""
    if frozen_root is not None:
        return frozen_root / "quest_renamer"
    return (module_file or Path(__file__)).resolve().parent


def configure_packaged_rendering(
    *,
    platform_name: str,
    frozen: bool,
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Use Qt's dependable software scene graph in packaged Linux apps.

    Some Wayland and driver combinations cannot create the OpenGL context selected
    by Qt Quick. That failure happens before a window can be shown. The dashboard
    is lightweight enough for Qt's software scene graph, and an explicit
    environment override still wins.
    """
    if not frozen or not platform_name.startswith("linux"):
        return
    target = os.environ if environment is None else environment
    target.setdefault("QT_QUICK_BACKEND", "software")


def support_tool_summary(
    package_root: Path,
    toolchain: Toolchain,
    *,
    older_firmware_ready: bool,
) -> str:
    catalog = load_tool_catalog(package_root / "resources" / "toolchain.json")
    return "; ".join(
        (
            f"Apktool {catalog['apktool'].version} "
            f"({'ready' if toolchain.apktool else 'missing'})",
            f"APK signer {catalog['uber_apk_signer'].version} "
            f"({'ready' if toolchain.signer else 'missing'})",
            f"Event Horizon {catalog['older_firmware_patch'].version} "
            f"({'ready' if older_firmware_ready else 'missing'})",
            f"Java {'ready' if toolchain.java else 'missing'}",
            f"keytool {'ready' if toolchain.keytool else 'missing'}",
        )
    )


def main() -> int:
    QCoreApplication.setOrganizationName("Quest APK Renamer")
    QCoreApplication.setApplicationName("Quest APK Renamer")
    QCoreApplication.setApplicationVersion(__version__)

    # The packaged QML set deliberately includes only the Basic control style.
    # Use it consistently on every desktop while still allowing an explicit
    # developer override before startup.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    smoke_test = "--smoke-test" in sys.argv[1:]
    launch_folder = initial_folder(sys.argv[1:])
    frozen = getattr(sys, "_MEIPASS", None)
    configure_packaged_rendering(
        platform_name=sys.platform,
        frozen=isinstance(frozen, str),
    )
    app = QApplication(sys.argv)
    package_root = package_resource_root(
        frozen_root=Path(frozen) if isinstance(frozen, str) else None
    )
    paths = platform_app_paths()
    toolchain = resolve_toolchain(
        resource_root=package_root,
        executable=Path(sys.executable),
        data_root=paths.data,
    )
    patch_candidates = []
    if override := os.environ.get("QAR_OLDER_FIRMWARE_PATCH"):
        patch_candidates.append(Path(override).expanduser())
    patch_candidates.extend(
        (
            package_root / "assets" / "patches" / "ovrplatform" / "libovrplatformloader.so",
            paths.data / "tools" / "libovrplatformloader.so",
        )
    )
    older_firmware_asset = next(
        (
            verified
            for candidate in patch_candidates
            if (verified := verified_older_firmware_asset(candidate)) is not None
        ),
        None,
    )
    icon = package_root / "assets" / "app-icon.svg"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    engine = QQmlApplicationEngine()
    inspector = LocalBundleInspector()
    analyzer = ApktoolAnalyzer(
        toolchain,
        signer_registry=package_root / "resources" / "known-signers.json",
    )
    preflight = AutomaticPreflight(
        tools_ready=toolchain.build_ready,
        tool_problems=toolchain.problems,
    )
    settings_store = JsonSettingsStore(paths.settings_file)
    activity_log = ActivityLog(paths.log_file)
    signing_root = paths.data / "signing"

    def log_migration(message: str) -> None:
        activity_log.append(message)

    try:
        migrate_legacy_signing_identity(
            paths.data,
            signing_root,
            toolchain.keytool,
            log=log_migration,
        )
    except LegacyIdentityMigrationError as exc:
        activity_log.append_event(
            "ERROR",
            "Legacy signing-key migration failed",
            (("Reason", str(exc)),),
        )
        try:
            signing_root.mkdir(parents=True, exist_ok=True)
            (signing_root / MIGRATION_ERROR_NAME).write_text(str(exc) + "\n", encoding="utf-8")
        except OSError:
            return 1
    device_service = AdbDeviceService(
        resource_root=package_root,
        executable=Path(sys.executable),
    )
    installer = AdbApkInstaller(
        resource_root=package_root,
        executable=Path(sys.executable),
    )
    build_engine = StagedApkBuildEngine(
        toolchain,
        signing_root=signing_root,
        cache_root=paths.cache / "build",
        older_firmware_asset=older_firmware_asset,
        move_to_trash=move_to_trash,
        recovery_record=paths.build_recovery_file,
    )
    controller = AppController(
        inspector=inspector,
        analyzer=analyzer,
        preflight_service=preflight,
        build_engine=build_engine,
        bundle_installer=installer,
        signing_manager=SigningIdentityManager(
            signing_root,
            keytool=toolchain.keytool,
        ),
        older_firmware_asset_available=older_firmware_asset is not None,
        device_service=device_service,
        settings_store=settings_store,
        activity_log=activity_log,
        move_to_trash=move_to_trash,
        paths=paths,
        support_tool_summary=support_tool_summary(
            package_root,
            toolchain,
            older_firmware_ready=older_firmware_asset is not None,
        ),
        parent=engine,
    )
    detailed_inspector = FullDecodeApkInspector(
        toolchain,
        signer_registry=package_root / "resources" / "known-signers.json",
        temporary_root=paths.cache / "inspector",
    )
    inspector_controller = InspectorController(
        detailed_inspector,
        parent=engine,
    )

    def activate_repaired_tools() -> None:
        nonlocal toolchain, older_firmware_asset
        toolchain = resolve_toolchain(
            resource_root=package_root,
            executable=Path(sys.executable),
            data_root=paths.data,
        )
        analyzer.toolchain = toolchain
        build_engine.toolchain = toolchain
        detailed_inspector.toolchain = toolchain
        older_firmware_asset = verified_older_firmware_asset(
            paths.data / "tools" / "libovrplatformloader.so"
        )
        build_engine.older_firmware_asset = older_firmware_asset
        controller.set_older_firmware_asset_available(older_firmware_asset is not None)
        controller.setSupportToolSummary(
            support_tool_summary(
                package_root,
                toolchain,
                older_firmware_ready=older_firmware_asset is not None,
            )
        )
        preflight.tools_ready = toolchain.build_ready
        preflight.tool_problems = toolchain.problems
        controller.refreshToolchainState()

    tool_controller = ToolController(
        PinnedToolManager(
            catalog_path=package_root / "resources" / "toolchain.json",
            resource_root=package_root,
            data_root=paths.data,
        ),
        activate_tools=activate_repaired_tools,
        parent=engine,
    )
    file_dialog_controller = FileDialogController(parent=engine)
    update_controller = UpdateController(
        GitHubReleaseChecker(
            load_update_channel(package_root / "resources" / "update-channel.json"),
            app_version=__version__,
        ),
        current_version=__version__,
        preferences=controller.update_preferences,
        save_dismissal=controller.dismiss_update_version,
        parent=engine,
    )
    bulk_controller = BulkController(
        inspector=inspector,
        analyzer=analyzer,
        preflight_service=preflight,
        build_engine=build_engine,
        bundle_installer=installer,
        settings_store=settings_store,
        device_snapshot=controller.current_device,
        external_busy=lambda: (
            controller.has_active_work()
            or inspector_controller.has_active_work()
            or tool_controller.has_active_work()
        ),
        move_to_trash=move_to_trash,
        parent=engine,
    )
    controller.set_external_busy_provider(
        lambda: (
            bulk_controller.has_active_work()
            or inspector_controller.has_active_work()
            or tool_controller.has_active_work()
        )
    )
    inspector_controller.set_external_busy_provider(
        lambda: (
            controller.has_active_work()
            or bulk_controller.has_active_work()
            or tool_controller.has_active_work()
        )
    )
    tool_controller.set_external_busy_provider(
        lambda: (
            controller.has_active_work()
            or bulk_controller.has_active_work()
            or inspector_controller.has_active_work()
        )
    )
    bulk_controller.busyChanged.connect(controller.refreshExternalBusy)
    inspector_controller.busyChanged.connect(controller.refreshExternalBusy)
    tool_controller.busyChanged.connect(controller.refreshExternalBusy)
    bulk_controller.busyChanged.connect(tool_controller.refreshExternalBusy)
    inspector_controller.busyChanged.connect(tool_controller.refreshExternalBusy)
    bulk_controller.activityMessage.connect(controller.recordActivity)
    inspector_controller.activityMessage.connect(controller.recordActivity)
    tool_controller.activityMessage.connect(controller.recordActivity)
    update_controller.activityMessage.connect(controller.recordActivity)
    controller.settingsChanged.connect(update_controller.refreshPreference)
    engine.rootContext().setContextProperty("appController", controller)
    engine.rootContext().setContextProperty("bulkController", bulk_controller)
    engine.rootContext().setContextProperty("inspectorController", inspector_controller)
    engine.rootContext().setContextProperty("toolController", tool_controller)
    engine.rootContext().setContextProperty("fileDialogController", file_dialog_controller)
    engine.rootContext().setContextProperty("updateController", update_controller)
    engine.rootContext().setContextProperty("appVersion", __version__)
    engine.load(QUrl.fromLocalFile(str(package_root / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    if launch_folder is not None:
        controller.chooseFolder(QUrl.fromLocalFile(str(launch_folder)))
    if smoke_test:
        QTimer.singleShot(250, app.quit)
    else:
        controller.startDeviceMonitoring()
        QTimer.singleShot(1400, update_controller.startAutomatic)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
