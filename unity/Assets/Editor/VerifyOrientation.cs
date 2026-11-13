using System;
using UnityEditor;
using UnityEngine;

// Batch-mode checks exercise Unity's actual quaternion and transform conventions.
public static class VerifyOrientation
{
    public static void Run()
    {
        Quaternion q = Quaternion.Euler(23, -47, 81);
        var robot = DesktopTarget.ToRobotRotation(q);
        if (Quaternion.Angle(q, DesktopTarget.ToUnityRotation(robot)) > 0.01f)
            throw new Exception("Quaternion round trip failed");
        Quaternion rq = new Quaternion(robot[1], robot[2], robot[3], robot[0]);
        Vector3 v = new Vector3(0.3f, -0.5f, 0.8f);
        Vector3 rotated = q*v;
        Vector3 mapped = new Vector3(rotated.x, -rotated.z, rotated.y);
        Vector3 expected = rq * new Vector3(v.x, -v.z, v.y);
        if ((mapped-expected).magnitude > 0.00001f)
            throw new Exception("Quaternion basis mapping failed");
        var initial = new DesktopTarget.TargetMessage {
            position = new [] {0f, -0.12f, 0.15f},
            orientation = robot, orientation_enabled = false };
        var roundTrip = JsonUtility.FromJson<DesktopTarget.TargetMessage>(JsonUtility.ToJson(initial));
        if (roundTrip.orientation_enabled || roundTrip.orientation.Length != 4)
            throw new Exception("Initial pose message serialization failed");
        var feedback = JsonUtility.FromJson<DesktopTarget.StateMessage>(
            "{\"v\":1,\"type\":\"state\",\"reachable\":true,\"orientation_requested\":false,\"orientation_error_deg\":0,\"goal_orientation\":[1,0,0,0]}");
        if (!feedback.reachable || feedback.goal_orientation.Length != 4)
            throw new Exception("Pose feedback deserialization failed");
        var sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        sphere.transform.localScale = Vector3.one * 0.015f;
        sphere.transform.rotation = q;
        TargetAxes.Ensure(sphere.transform);
        var root = sphere.transform.Find("Tool orientation axes");
        if (root.childCount != 6 || (root.lossyScale-Vector3.one).magnitude > 0.001f)
            throw new Exception("Target axes size/hierarchy failed");
        TargetAxes.Ensure(sphere.transform);
        if (sphere.transform.childCount != 1)
            throw new Exception("Duplicate target axes");
        UnityEngine.Object.DestroyImmediate(sphere);
        Debug.Log("ORIENTATION_UNITY_CHECKS_PASSED: quaternion mapping, round trip, visible axes scale, idempotence");
    }
}
