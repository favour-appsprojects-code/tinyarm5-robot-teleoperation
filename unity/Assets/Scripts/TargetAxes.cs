using UnityEngine;

// Draw robot-tool axes in Unity coordinates. Robot Y maps to Unity -Z,
// robot Z maps to Unity +Y, so colours match the MuJoCo tip axes exactly.
public static class TargetAxes
{
    public static void Ensure(Transform target)
    {
        if (target.Find("Tool orientation axes") != null) return;
        var root = new GameObject("Tool orientation axes").transform;
        root.SetParent(target, false);
        Vector3 scale = target.lossyScale;
        root.localScale = new Vector3(1/scale.x, 1/scale.y, 1/scale.z);
        AddAxis(root, "Tool +X (red)", Vector3.right, Color.red);
        AddAxis(root, "Tool +Y (green)", Vector3.back, Color.green);
        AddAxis(root, "Tool +Z (blue)", Vector3.up, new Color(0,0.4f,1));
    }

    static void AddAxis(Transform root, string name, Vector3 direction, Color color)
    {
        var material = new Material(Shader.Find("Unlit/Color"));
        material.color = color;
        var rod = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        rod.name = name;
        rod.transform.SetParent(root, false);
        rod.transform.localPosition = direction * 0.0275f;
        rod.transform.localRotation = Quaternion.FromToRotation(Vector3.up, direction);
        rod.transform.localScale = new Vector3(0.0025f,0.0275f,0.0025f);
        rod.GetComponent<Renderer>().sharedMaterial = material;
        Object.DestroyImmediate(rod.GetComponent<Collider>());
        var end = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        end.name = "Positive endpoint";
        end.transform.SetParent(root, false);
        end.transform.localPosition = direction * 0.055f;
        end.transform.localScale = Vector3.one * 0.006f;
        end.GetComponent<Renderer>().sharedMaterial = material;
        Object.DestroyImmediate(end.GetComponent<Collider>());
    }
}
