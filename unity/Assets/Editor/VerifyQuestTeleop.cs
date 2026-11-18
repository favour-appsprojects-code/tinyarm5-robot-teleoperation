using System;
using UnityEngine;

// Batch checks for the Quest teleoperation additions (no headset required):
//   Unity.exe -batchmode -quit -projectPath unity -executeMethod VerifyQuestTeleop.Run -logFile verify.log
public static class VerifyQuestTeleop
{
    public static void Run()
    {
        try {
            VerifyHardwareIntegration.Run();
            // One Euro: suppresses jitter when still, follows quickly when moving.
            var filter = new OneEuroFilter3(1f, 4f);
            filter.Reset(Vector3.zero);
            var rng = new System.Random(1);
            float maxStill = 0f;
            for (int i = 0; i < 200; i++) {
                var noise = new Vector3((float)rng.NextDouble()-0.5f, (float)rng.NextDouble()-0.5f, (float)rng.NextDouble()-0.5f) * 0.004f;
                maxStill = Mathf.Max(maxStill, filter.Filter(noise, 1f/72f).magnitude);
            }
            if (maxStill > 0.0015f) throw new Exception($"Filter jitter too high: {maxStill*1000:F2} mm");
            Vector3 moving = Vector3.zero;
            for (int i = 1; i <= 36; i++) moving = filter.Filter(new Vector3(0.3f * i / 72f, 0, 0), 1f/72f);
            float lag = 0.3f * 36 / 72f - moving.x;
            if (lag > 0.03f) throw new Exception($"Filter lag too high while moving: {lag*1000:F1} mm");

            var state = JsonUtility.FromJson<DesktopTarget.StateMessage>(
                "{\"v\":1,\"type\":\"state\",\"seq\":3,\"reachable\":true,\"status_flags\":[\"Simulation Mode\",\"Recording Commands\"]," +
                "\"sim_links\":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],\"cube_position\":[0.08,-0.17,0.0125],\"cube_grasped\":true," +
                "\"task_elapsed_s\":4.5,\"receiver_state\":\"physical_disabled\",\"recording_file\":\"x.jsonl\"}");
            if (state.status_flags.Length != 2 || state.status_flags[1] != "Recording Commands" || state.sim_links.Length != 21 ||
                !state.cube_grasped || state.receiver_state != "physical_disabled")
                throw new Exception("Extended state deserialization failed");

            var config = JsonUtility.FromJson<TeleopConfig>("{\"serverAddress\":\"auto\",\"serverPort\":5006,\"fineScale\":0.2}");
            if (config.serverAddress != "auto" || config.serverPort != 5006 || TeleopConfig.Pick(config.fineScale, 1f) != 0.2f ||
                TeleopConfig.Pick(config.normalScale, 1f) != 1f)
                throw new Exception("Teleop config parsing failed");
            Debug.Log($"QUEST_TELEOP_CHECKS_PASSED: filter still-jitter {maxStill*1000:F2} mm, moving lag {lag*1000:F1} mm, state/config parsing");
            if (Application.isBatchMode) UnityEditor.EditorApplication.Exit(0);
        } catch (Exception ex) {
            Debug.LogException(ex);
            if (Application.isBatchMode) UnityEditor.EditorApplication.Exit(1);
            else throw;
        }
    }
}
