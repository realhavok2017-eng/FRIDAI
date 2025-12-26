# FRIDAI Session Notes - December 26, 2025

## Summary
Upgraded Android avatar from basic OpenGL ES 2.0 to premium OpenGL ES 3.0 with advanced effects. Used incremental approach - testing each effect individually before combining.

---

## Android Avatar v2.0 - What We Built

### Final Stack (all kept):
1. **V1 Base** - Icosahedron with fresnel, audio-reactive vertex displacement
2. **Subsurface Scattering** - Light passes through translucent sphere
3. **HDR Bloom** - Multi-pass post-processing with gaussian blur
4. **Volumetric Core** - Raymarched swirling energy inside

### Effects Tested & Rejected:
- **Enhanced Fresnel** - Too dramatic, changed the look too much
- **Procedural Normal Mapping** - Added surface noise but didn't improve appearance

---

## Technical Implementation Details

### Subsurface Scattering (KEPT)
Makes sphere translucent - light actually passes through from behind.

```glsl
// Key: backFacing detection and transmission
float backFacing = max(dot(vNormal, -lightDir), 0.0);
float transmission = pow(backFacing, 1.5) * 0.6;
float backscatter = pow(max(dot(vNormal, -viewDir), 0.0), 2.0) * 0.35;

// Warm tint for transmitted light
vec3 transmitColor = uColor * 1.5 + vec3(0.15, 0.08, 0.0);
finalColor += transmitColor * transmission;

// Alpha: transparent center, solid edges
float alpha = (0.25 + fresnel * 0.6 + transmission * 0.3) * uAlpha;
```

### HDR Bloom (KEPT)
Requires OpenGL ES 3.0 for RGBA16F framebuffers.

**Pipeline:**
1. Render scene to HDR FBO (hdrFBO with hdrTexture)
2. Extract bright pixels > 0.4 threshold to bloomFBO1
3. Horizontal gaussian blur (bloomFBO1 → bloomFBO2)
4. Vertical gaussian blur (bloomFBO2 → bloomFBO1)
5. Composite: scene + bloom to screen

**Key code for FBO setup:**
```kotlin
GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D, 0, GLES30.GL_RGBA16F,
    width, height, 0, GLES30.GL_RGBA, GLES30.GL_HALF_FLOAT, null)
```

**Bloom strength is audio-reactive:**
```kotlin
GLES20.glUniform1f(..., "uBloomStrength"), 0.6f + glowIntensity * 0.4f)
```

### Volumetric Core (KEPT)
Raymarched noise clouds inside the sphere.

```glsl
for (float t = 0.0; t < 0.8; t += 0.04) {
    vec3 pos = rayDir * t;
    float dist = length(pos);
    if (dist < 0.5) {
        vec3 noisePos = pos * 4.0 + uTime * 0.8;
        float n = noise(noisePos) + noise(noisePos * 2.0) * 0.5;
        float swirl = sin(atan(pos.y, pos.x) * 3.0 + uTime * 2.0 + dist * 8.0) * 0.3;
        n += swirl + uAudioLevel * sin(dist * 12.0 + uTime * 6.0) * 0.4;
        density += smoothstep(0.2, 0.6, n) * (1.0 - dist / 0.5) * 0.08;
    }
}
```

---

## File Locations

### Android Avatar Builds
```
C:/Users/Owner/FRIDAI-Avatar/builds/android/
├── FridaiGLAvatar_v1_backup.kt    # Original v1 (safe backup)
├── FridaiGLAvatar_v1_sss.kt       # v1 + SSS only
├── FridaiGLAvatar_v1_sss_bloom.kt # v1 + SSS + Bloom
└── FridaiGLAvatar_v2_final.kt     # Full version (CURRENT)
```

### Active Android File
```
C:/Users/Owner/FridaiAndroid/app/src/main/java/com/fridai/app/ui/FridaiGLAvatar.kt
```

### Git Repos Updated
- `FRIDAI-Avatar` - All builds pushed
- `VoiceClaude` (FRIDAI) - Session state pushed

---

## How to Restore/Rollback

### To restore v1 (original):
```bash
cp "C:/Users/Owner/FRIDAI-Avatar/builds/android/FridaiGLAvatar_v1_backup.kt" \
   "C:/Users/Owner/FridaiAndroid/app/src/main/java/com/fridai/app/ui/FridaiGLAvatar.kt"
```

### To restore v2 final:
```bash
cp "C:/Users/Owner/FRIDAI-Avatar/builds/android/FridaiGLAvatar_v2_final.kt" \
   "C:/Users/Owner/FridaiAndroid/app/src/main/java/com/fridai/app/ui/FridaiGLAvatar.kt"
```

### Build & Install:
```bash
cd C:/Users/Owner/FridaiAndroid
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Key Lessons Learned

1. **Test effects individually** - Don't stack everything at once
2. **ES 3.0 required for HDR** - RGBA16F textures need ES 3.0
3. **Alpha clamping critical** - Android crashes if alpha > 1.0, use `.coerceIn(0f, 1f)`
4. **SSS needs real transparency** - Not just color tinting, actual alpha changes
5. **Volumetric is expensive** - Keep step count low (0.04 step = 20 iterations)
6. **Bloom at half-res** - Saves GPU, looks softer anyway

---

## Audio-Reactive Displacement Formula (preserved from PWA)
```kotlin
val wave1 = sin(phi * 4 + time * 3) * 0.02f
val wave2 = sin(angle * 3 + time * 2) * 0.015f
val wave3 = sin(phi * 2 + angle * 2 + time * 4) * 0.01f
val audioWave = displacement * sin(phi * 8 + angle * 6 + time * 5) * 0.15f
```

---

## What's Still Available to Add (didn't do today)
- **Particles** - Orbiting sparkles around sphere
- Could add later on top of v2

---

## FRIDAI Server Status
- Running on localhost:5000
- Cloudflare tunnel: fridai.fridai.me
- Started independently, survives terminal close
