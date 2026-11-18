using UnityEngine;

// One Euro filter (Casiez et al. 2012): low lag when moving fast, strong
// jitter suppression when nearly still. Ideal for tracked-hand positions.
public class OneEuroFilter3
{
    public float minCutoff, beta, derivativeCutoff;
    Vector3 value, derivative;
    bool initialized;

    public OneEuroFilter3(float minCutoff = 1f, float beta = 4f, float derivativeCutoff = 1f)
    { this.minCutoff = minCutoff; this.beta = beta; this.derivativeCutoff = derivativeCutoff; }

    static float Alpha(float cutoff, float dt) {
        float tau = 1f / (2f * Mathf.PI * cutoff);
        return 1f / (1f + tau / Mathf.Max(dt, 1e-4f));
    }

    public void Reset(Vector3 start) { value = start; derivative = Vector3.zero; initialized = true; }

    public Vector3 Filter(Vector3 sample, float dt)
    {
        if (!initialized) { Reset(sample); return sample; }
        Vector3 rawDerivative = (sample - value) / Mathf.Max(dt, 1e-4f);
        derivative = Vector3.Lerp(derivative, rawDerivative, Alpha(derivativeCutoff, dt));
        float cutoff = minCutoff + beta * derivative.magnitude;
        value = Vector3.Lerp(value, sample, Alpha(cutoff, dt));
        return value;
    }
}
