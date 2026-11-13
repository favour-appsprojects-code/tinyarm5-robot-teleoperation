using System;
using UnityEngine;

public static class VerifyHardwareIntegration
{
    public static void Run()
    {
        VerifyOrientation.Run();
        var command = new DesktopTarget.TargetMessage {
            position = new [] {0f,-0.22f,0.16f}, orientation = new [] {1f,0f,0f,0f},
            action="preview", gripper="closed", preview_id="abc" };
        var decoded = JsonUtility.FromJson<DesktopTarget.TargetMessage>(JsonUtility.ToJson(command));
        if (decoded.action!="preview" || decoded.gripper!="closed" || decoded.preview_id!="abc")
            throw new Exception("Control serialization failed");
        var preview = new GameObject("Verification goal preview").AddComponent<RobotPreview>();
        var links = new float[21];
        for (int i=0;i<7;i++) { links[3*i]=i*0.01f; links[3*i+1]=-i*0.02f; links[3*i+2]=i*0.03f; }
        preview.UpdatePreview(links);
        if (preview.transform.childCount!=6) throw new Exception("Preview link hierarchy invalid");
        Vector3 expected = new Vector3(0.005f,0.015f,0.01f);
        if ((preview.transform.GetChild(0).position-expected).magnitude>1e-6f)
            throw new Exception("Robot preview coordinate mapping failed");
        UnityEngine.Object.DestroyImmediate(preview.gameObject);
        Debug.Log("HARDWARE_UNITY_CHECKS_PASSED: pose/control serialization, preview skeleton, XR adapter compilation");
    }
}
