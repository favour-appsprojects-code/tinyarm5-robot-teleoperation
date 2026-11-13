using UnityEngine;

// Lightweight FK skeleton of the accepted IK goal. It is a preview, not robot telemetry.
public class RobotPreview : MonoBehaviour
{
    public Transform robotBase;
    Transform[] rods;
    Material material;

    public void UpdatePreview(float[] links)
    {
        if (links == null || links.Length != 21) return;
        if (rods == null) {
            rods = new Transform[6];
            material = new Material(Shader.Find("Unlit/Color"));
            material.color = new Color(1,0.65f,0.1f);
            for (int i=0; i<6; i++) {
                var part = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                part.name = "Goal preview link " + i;
                part.transform.SetParent(transform,false);
                part.GetComponent<Renderer>().sharedMaterial = material;
                if (Application.isPlaying) Destroy(part.GetComponent<Collider>());
                else DestroyImmediate(part.GetComponent<Collider>());
                rods[i] = part.transform;
            }
        }
        for (int i=0; i<6; i++) {
            Vector3 a = Point(links,i), b = Point(links,i+1), delta = b-a;
            rods[i].position = (a+b)*0.5f;
            rods[i].rotation = delta.sqrMagnitude > 1e-10f ? Quaternion.FromToRotation(Vector3.up,delta) : Quaternion.identity;
            rods[i].localScale = new Vector3(0.006f,delta.magnitude*0.5f,0.006f);
        }
    }
    Vector3 Point(float[] p, int i) {
        Vector3 point = new Vector3(p[3*i],p[3*i+2],-p[3*i+1]);
        return robotBase == null ? point : robotBase.TransformPoint(point);
    }
    void OnDestroy() {
        if (material == null) return;
        if (Application.isPlaying) Destroy(material); else DestroyImmediate(material);
    }
}
