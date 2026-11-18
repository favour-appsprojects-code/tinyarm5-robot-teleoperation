using UnityEngine;

// Mirrors Python/MuJoCo state in the headset: the simulated arm (cyan), the
// simulated cube and cup, the gripper state at the tool tip and a base marker.
// All of it is simulation output, not physical robot telemetry.
public class SceneMirror : MonoBehaviour
{
    public DesktopTarget teleop;
    RobotPreview simArm;
    Transform cube, cup, gripperDot, baseMarker;
    Material cubeMaterial, cupMaterial, gripperMaterial;

    static Material Unlit(Color color) { var m = new Material(Shader.Find("Unlit/Color")); m.color = color; return m; }
    static Transform Primitive(PrimitiveType type, string name, Transform parent, Material material) {
        var go = GameObject.CreatePrimitive(type);
        go.name = name;
        Destroy(go.GetComponent<Collider>());
        go.GetComponent<Renderer>().sharedMaterial = material;
        go.transform.SetParent(parent, false);
        return go.transform;
    }

    void Start()
    {
        if (teleop == null) teleop = FindFirstObjectByType<DesktopTarget>();
        simArm = new GameObject("Simulated arm (MuJoCo state, cyan)").AddComponent<RobotPreview>();
        simArm.color = new Color(0.1f, 0.85f, 1f);
        simArm.thickness = 0.01f;
        simArm.robotBase = teleop.robotBase;
        cubeMaterial = Unlit(new Color(0.9f, 0.2f, 0.2f));
        cupMaterial = Unlit(new Color(0.2f, 0.4f, 0.95f));
        gripperMaterial = Unlit(Color.gray);
        cube = Primitive(PrimitiveType.Cube, "Simulated cube", transform, cubeMaterial);
        cup = Primitive(PrimitiveType.Cylinder, "Simulated cup", transform, cupMaterial);
        gripperDot = Primitive(PrimitiveType.Sphere, "Gripper state", transform, gripperMaterial);
        gripperDot.localScale = Vector3.one * 0.018f;
        if (teleop.robotBase != null) {
            baseMarker = Primitive(PrimitiveType.Cylinder, "Robot base marker (align with real base)", teleop.robotBase, Unlit(new Color(1f, 1f, 1f)));
            baseMarker.localScale = new Vector3(0.09f, 0.0015f, 0.09f);
            baseMarker.localPosition = Vector3.zero;
            var forward = Primitive(PrimitiveType.Cube, "Robot -Y (reach direction)", teleop.robotBase, Unlit(new Color(0.1f, 0.9f, 0.2f)));
            forward.localScale = new Vector3(0.006f, 0.003f, 0.08f);
            forward.localPosition = new Vector3(0, 0.002f, 0.06f);
        }
        SetVisible(false);
    }

    void SetVisible(bool visible) {
        cube.gameObject.SetActive(visible); cup.gameObject.SetActive(visible); gripperDot.gameObject.SetActive(visible);
    }

    Vector3 ToWorld(float[] p, int offset = 0) {
        Vector3 local = new Vector3(p[offset], p[offset + 2], -p[offset + 1]);
        return teleop.robotBase == null ? local : teleop.robotBase.TransformPoint(local);
    }

    void Update()
    {
        var s = teleop.State;
        if (s == null || !teleop.Connected) { SetVisible(false); return; }
        SetVisible(true);
        simArm.UpdatePreview(s.sim_links);
        Quaternion baseRotation = teleop.robotBase == null ? Quaternion.identity : teleop.robotBase.rotation;
        float scale = teleop.robotBase == null ? 1f : teleop.robotBase.lossyScale.x;
        if (s.cube_position != null && s.cube_position.Length == 3) {
            cube.position = ToWorld(s.cube_position);
            cube.rotation = baseRotation;
            cube.localScale = Vector3.one * Mathf.Max(0.005f, s.cube_size) * scale;
            cubeMaterial.color = s.cube_grasped ? new Color(1f, 0.55f, 0.1f) : new Color(0.9f, 0.2f, 0.2f);
        }
        if (s.cup_position != null && s.cup_position.Length == 3) {
            cup.position = ToWorld(s.cup_position) + baseRotation * Vector3.up * (s.cup_height * 0.5f * scale);
            cup.rotation = baseRotation;
            cup.localScale = new Vector3(s.cup_radius * 2f, s.cup_height * 0.5f, s.cup_radius * 2f) * scale;
            cupMaterial.color = s.cube_in_cup ? new Color(0.2f, 0.9f, 0.4f) : new Color(0.2f, 0.4f, 0.95f);
        }
        if (s.sim_links != null && s.sim_links.Length == 21) gripperDot.position = ToWorld(s.sim_links, 18);
        gripperMaterial.color = s.gripper_state == "closed" ? new Color(0.95f, 0.15f, 0.1f) :
                                s.gripper_state == "open" ? new Color(0.1f, 0.85f, 0.2f) : Color.gray;
    }
}
