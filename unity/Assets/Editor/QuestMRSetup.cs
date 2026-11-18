using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SpatialTracking;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;

// One-click Quest 3 mixed-reality configuration for the EXISTING project.
// Android-only XR settings: the Standalone/Editor desktop demo is untouched.
// Menu: TinyARM > Quest MR > ...   Batch: -executeMethod QuestMRSetup.BatchBuild
public static class QuestMRSetup
{
    public const string DesktopScene = "Assets/Scenes/DesktopDemo.unity";
    public const string QuestScene = "Assets/Scenes/QuestMR.unity";
    public const string PackageName = "edu.louisville.tinyarm5.teleop";
    public const string ApkPath = "Builds/TinyARM5-Quest.apk";

    static readonly string[] OpenXRFeatures = {
        "com.unity.openxr.feature.metaquest",               // Unity Meta Quest support
        "com.meta.openxr.feature.metaxr",                   // Meta XR (passthrough, OVRManager)
        "com.unity.openxr.feature.input.handtracking",      // XR Hands subsystem
        "com.unity.openxr.feature.input.metahandtrackingaim",
        "com.unity.openxr.feature.input.oculustouch",       // controller fallback
        "com.unity.openxr.feature.input.metaquestplus",
    };

    [MenuItem("TinyARM/Quest MR/1. Configure Project For Quest 3")]
    public static void ConfigureProject()
    {
        // --- Player settings (Android) ---
        var android = NamedBuildTarget.Android;
        PlayerSettings.companyName = "UofL Immersive Robotics";
        PlayerSettings.productName = "TinyARM5 Teleop";
        PlayerSettings.SetApplicationIdentifier(android, PackageName);
        PlayerSettings.SetScriptingBackend(android, ScriptingImplementation.IL2CPP);
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
        PlayerSettings.Android.forceInternetPermission = true;   // UDP to the Python laptop
        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
        PlayerSettings.colorSpace = ColorSpace.Linear;
        PlayerSettings.runInBackground = true;
        EditorUserBuildSettings.androidBuildSubtarget = MobileTextureSubtarget.ASTC;

        // --- XR Plug-in Management: OpenXR on Android only ---
        EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.k_SettingsKey, out XRGeneralSettingsPerBuildTarget perTarget);
        if (perTarget == null) {
            Directory.CreateDirectory("Assets/XR");
            perTarget = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
            AssetDatabase.CreateAsset(perTarget, "Assets/XR/XRGeneralSettingsPerBuildTarget.asset");
            EditorBuildSettings.AddConfigObject(XRGeneralSettings.k_SettingsKey, perTarget, true);
        }
        if (!perTarget.HasManagerSettingsForBuildTarget(BuildTargetGroup.Android))
            perTarget.CreateDefaultManagerSettingsForBuildTarget(BuildTargetGroup.Android);
        var general = perTarget.SettingsForBuildTarget(BuildTargetGroup.Android);
        general.InitManagerOnStart = true;
        if (!XRPackageMetadataStore.AssignLoader(general.Manager, "UnityEngine.XR.OpenXR.OpenXRLoader", BuildTargetGroup.Android))
            Debug.LogWarning("[TinyARM] OpenXR loader assignment reported false (it may already be assigned).");
        EditorUtility.SetDirty(perTarget);
        EditorUtility.SetDirty(general);
        EditorUtility.SetDirty(general.Manager);

        // --- OpenXR features ---
        FeatureHelpers.RefreshFeatures(BuildTargetGroup.Android);
        foreach (var id in OpenXRFeatures) {
            var feature = FeatureHelpers.GetFeatureWithIdForBuildTarget(BuildTargetGroup.Android, id);
            if (feature == null) { Debug.LogError($"[TinyARM] OpenXR feature not found: {id}"); continue; }
            feature.enabled = true;
            EditorUtility.SetDirty(feature);
        }
        // Avoid two providers of XR_EXT_hand_tracking data.
        var duplicate = FeatureHelpers.GetFeatureWithIdForBuildTarget(BuildTargetGroup.Android, "com.meta.openxr.feature.handtrackingdatasource");
        if (duplicate != null && duplicate.enabled) { duplicate.enabled = false; EditorUtility.SetDirty(duplicate); }
        var openxr = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
        if (openxr != null) {
            // Multi-pass renders every built-in shader in both eyes (the HUD uses
            // legacy TextMesh). This scene is tiny, so the cost is irrelevant.
            openxr.renderMode = OpenXRSettings.RenderMode.MultiPass;
            EditorUtility.SetDirty(openxr);
        }

        // --- Meta project config: hands + passthrough in the manifest ---
        var meta = OVRProjectConfig.CachedProjectConfig;
        meta.handTrackingSupport = OVRProjectConfig.HandTrackingSupport.ControllersAndHands;
        meta.insightPassthroughSupport = OVRProjectConfig.FeatureSupport.Required;
        OVRProjectConfig.CommitProjectConfig(meta);

        AssetDatabase.SaveAssets();
        Debug.Log("[TinyARM] Quest 3 project configuration applied (Android only). Review Project Settings > XR Plug-in Management > Project Validation.");
    }

    [MenuItem("TinyARM/Quest MR/2. Create Or Update QuestMR Scene")]
    public static void CreateScene()
    {
        if (!File.Exists(QuestScene)) {
            if (!AssetDatabase.CopyAsset(DesktopScene, QuestScene))
                throw new InvalidOperationException("Could not copy " + DesktopScene);
        }
        var scene = EditorSceneManager.OpenScene(QuestScene, OpenSceneMode.Single);
        var app = UnityEngine.Object.FindFirstObjectByType<DesktopTarget>();
        if (app == null) throw new InvalidOperationException("QuestMR scene has no DesktopTarget");
        app.serverAddress = "auto";
        app.serverPort = 5006;

        // Tracking origin + head camera driven by the XR runtime.
        var originObject = GameObject.Find("XR Origin (TinyARM)");
        Transform origin = originObject != null ? originObject.transform : null;
        if (origin == null) {
            var legacy = UnityEngine.Object.FindFirstObjectByType<QuestControllerTarget>();
            origin = legacy != null ? legacy.transform : new GameObject().transform;
            origin.name = "XR Origin (TinyARM)";
        }
        origin.position = Vector3.zero; origin.rotation = Quaternion.identity;
        var camera = Camera.main;
        if (camera == null) throw new InvalidOperationException("Main camera missing");
        camera.transform.SetParent(origin, false);
        camera.transform.localPosition = new Vector3(0, 1.4f, 0);
        camera.transform.localRotation = Quaternion.identity;
        camera.stereoTargetEye = StereoTargetEyeMask.Both;
        var pose = Ensure<TrackedPoseDriver>(camera.gameObject);
        pose.SetPoseSource(TrackedPoseDriver.DeviceType.GenericXRDevice, TrackedPoseDriver.TrackedPose.Center);
        pose.trackingType = TrackedPoseDriver.TrackingType.RotationAndPosition;
        pose.updateType = TrackedPoseDriver.UpdateType.UpdateAndBeforeRender;

        // Robot base at table height in front of the user; the target becomes its
        // child so it always stays fixed in robot coordinates.
        if (app.robotBase == null) {
            var baseFrame = new GameObject("Virtual robot base - PLACE BASE to align with real robot").transform;
            app.robotBase = baseFrame;
        }
        app.robotBase.SetParent(origin, false);
        app.robotBase.localPosition = new Vector3(0, 0.75f, 0.45f);
        app.robotBase.localRotation = Quaternion.identity;
        app.robotBase.localScale = Vector3.one;
        app.target.SetParent(app.robotBase, false);
        app.target.localPosition = new Vector3(0, 0.15f, 0.12f);
        app.target.localScale = Vector3.one * 0.025f;

        // Desktop-only scene objects (reference plane / axis gizmos) would hide the real table.
        foreach (var name in new[] { "Reference plane (not a reachability guarantee)", "Robot X / Unity X", "Robot -Y / Unity Z", "Robot Z / Unity Y", "Light" }) {
            var go = GameObject.Find(name);
            if (go != null && go.GetComponent<Light>() == null) go.SetActive(false);
        }

        var hands = Ensure<HandTeleopController>(origin.gameObject);
        hands.teleop = app; hands.trackingOrigin = origin;
        var controller = Ensure<QuestControllerTarget>(origin.gameObject);
        controller.teleoperation = app; controller.trackingOrigin = origin; controller.headCamera = camera.transform;
        var mr = Ensure<MixedRealitySetup>(origin.gameObject);
        mr.xrCamera = camera;

        var hudObject = FindOrCreate("TinyARM HUD");
        hudObject.transform.SetParent(origin, false);
        var hud = Ensure<XrHud>(hudObject);
        hud.teleop = app; hud.hands = hands; hud.trackingOrigin = origin; hud.head = camera.transform;
        var mirrorObject = FindOrCreate("Simulation mirror");
        Ensure<SceneMirror>(mirrorObject).teleop = app;

        // Passthrough: OVRManager + underlay layer; camera background is cleared to alpha 0.
        var managerObject = FindOrCreate("Meta Passthrough (OVRManager)");
        var manager = Ensure<OVRManager>(managerObject);
        manager.isInsightPassthroughEnabled = true;
        manager.trackingOriginType = OVRManager.TrackingOrigin.FloorLevel;
        Ensure<OVRPassthroughLayer>(managerObject);
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0, 0, 0, 0);

        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        // QuestMR first (used by Android builds); desktop scene kept in the list.
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(QuestScene, true), new EditorBuildSettingsScene(DesktopScene, false) };
        Debug.Log("[TinyARM] QuestMR scene ready. Server address 'auto' (LAN discovery) or teleop_config.json overrides it.");
    }

    // Explicit == null: in the Editor a missing component can be Unity's "fake null", which ?? does not catch.
    static T Ensure<T>(GameObject go) where T : Component
    {
        var component = go.GetComponent<T>();
        if (component == null) component = go.AddComponent<T>();
        return component;
    }

    static GameObject FindOrCreate(string name)
    {
        var go = GameObject.Find(name);
        return go != null ? go : new GameObject(name);
    }

    [MenuItem("TinyARM/Quest MR/3. Build Quest APK")]
    public static void BuildApk() => Build(false);

    // Installs and launches on the USB-connected Quest (Developer Mode + USB debugging allowed).
    [MenuItem("TinyARM/Quest MR/4. Build And Run On Connected Quest")]
    public static void BuildAndRun() => Build(true);

    static void Build(bool run)
    {
        if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android &&
            !EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android))
            throw new BuildFailedException("Could not switch to Android. Install Android Build Support for 6000.4.8f1.");
        Directory.CreateDirectory(Path.GetDirectoryName(ApkPath));
        var options = new BuildPlayerOptions {
            scenes = new[] { QuestScene }, locationPathName = ApkPath,
            target = BuildTarget.Android, targetGroup = BuildTargetGroup.Android, options = run ? BuildOptions.AutoRunPlayer : BuildOptions.None };
        BuildReport report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;
        Debug.Log($"[TinyARM] Build {summary.result}: {summary.outputPath} {summary.totalSize/1048576f:F1} MB, " +
                  $"{summary.totalErrors} error(s), {summary.totalWarnings} warning(s), {summary.totalTime}");
        if (summary.result != BuildResult.Succeeded) throw new BuildFailedException("Quest APK build failed: " + summary.result);
    }

    // Unity.exe -batchmode -quit -projectPath unity -executeMethod QuestMRSetup.BatchBuild -logFile build.log
    public static void BatchBuild()
    {
        try { ConfigureProject(); CreateScene(); BuildApk(); EditorApplication.Exit(0); }
        catch (Exception ex) { Debug.LogException(ex); EditorApplication.Exit(1); }
    }

    public static void BatchSetupOnly()
    {
        try { ConfigureProject(); CreateScene(); EditorApplication.Exit(0); }
        catch (Exception ex) { Debug.LogException(ex); EditorApplication.Exit(1); }
    }
}
