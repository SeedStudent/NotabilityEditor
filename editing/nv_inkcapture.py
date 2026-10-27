"""Incremental real-time stroke stabilizer for new pen/highlighter strokes.

Each incoming sample finalizes the preceding interior vertex using its two
neighbors. The newest point stays under the cursor/stylus: no buffered latency,
look-ahead timer, global re-smoothing, or modification of existing NTB strokes.
"""
import math


def stabilize_middle_point(before, middle, after, width, strength=0.85):
    """Return a gently smoothed previous vertex, bounded near its raw position.

    The input locations are successive *raw* samples. Unlike smoothing an
    entire stroke after release, this works with only three points and does
    not delay the latest tip sample.
    """
    try:
        a=tuple(float(v) for v in before)
        b=tuple(float(v) for v in middle)
        c=tuple(float(v) for v in after)
        width=float(width)
        strength=float(strength)
    except (TypeError, ValueError):
        return tuple(middle)
    if not all(math.isfinite(v) for v in (*a,*b,*c,width,strength)):
        return tuple(middle)
    strength=max(0.0,min(1.0,strength))
    if not strength:
        return b
    ux,uy=b[0]-a[0],b[1]-a[1]
    vx,vy=c[0]-b[0],c[1]-b[1]
    ulen=math.hypot(ux,uy);vlen=math.hypot(vx,vy)
    if ulen<1e-8 or vlen<1e-8:
        return b
    # Sharp, deliberate corners survive. Small jitter still gets reduced.
    cosine=max(-1.0,min(1.0,(ux*vx+uy*vy)/(ulen*vlen)))
    if cosine<0.5 and min(ulen,vlen)>max(2.0,abs(width)*0.65):
        return b
    weighted=((a[0]+2*b[0]+c[0])*0.25,(a[1]+2*b[1]+c[1])*0.25)
    dx=strength*(weighted[0]-b[0])
    dy=strength*(weighted[1]-b[1])
    cap=max(0.28,min(1.5,abs(width)*0.5))
    distance=math.hypot(dx,dy)
    if distance>cap:
        dx*=cap/distance
        dy*=cap/distance
    return (b[0]+dx,b[1]+dy)
