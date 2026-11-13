using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Optional additions to the current scene. Never changes the working desktop
// scene until this menu is explicitly invoked; does not install/enable a provider.
public static class QuestPreparation
{
    [MenuItem("TinyARM/Prepare Controller Rig In Current Scene")]
    public static void Prepare()
    {
        var app = Object.FindFirstObjectByType<DesktopTarget>();
        if (app == null) throw new System.InvalidOperationException("Open DesktopDemo first");
        if (Object.FindFirstObjectByType<QuestControllerTarget>() != null) return;
        var camera = Camera.main;
        if (camera == null) throw new System.InvalidOperationException("Main camera missing");
        Undo.RecordObject(app,"Add controller rig");
        var origin = new GameObject("Quest Tracking Origin (OpenXR provider required)").transform;
        Undo.RegisterCreatedObjectUndo(origin.gameObject,"Add controller rig");
        Undo.SetTransformParent(camera.transform,origin,"Parent headset camera");
        camera.transform.localPosition = Vector3.zero;
        camera.transform.localRotation = Quaternion.identity;
        camera.stereoTargetEye = StereoTargetEyeMask.Both;
        if (app.robotBase == null) {
            var baseFrame = new GameObject("Virtual robot base - CALIBRATE before physical use").transform;
            baseFrame.position = new Vector3(0,0.8f,0.6f);
            app.robotBase = baseFrame;
            app.target.position = baseFrame.TransformPoint(new Vector3(0,0.16f,0.22f));
        }
        var controller = origin.gameObject.AddComponent<QuestControllerTarget>();
        controller.teleoperation=app; controller.trackingOrigin=origin; controller.headCamera=camera.transform;
        EditorSceneManager.MarkSceneDirty(app.gameObject.scene);
        Debug.Log("Controller rig prepared. Set Python PC LAN address, install Android Build Support and configure OpenXR before deploying. Physical output remains locked.");
    }
}
