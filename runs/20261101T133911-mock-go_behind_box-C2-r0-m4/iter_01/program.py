import math
sx, sy, _ = api.get_robot_pose()
bx, by, _ = api.get_object_pose("blue_box")
d = math.hypot(bx - sx, by - sy)
ux, uy = (bx - sx) / d, (by - sy) / d
nx, ny = -uy, ux
side = -1.0 if by > 0 else 1.0
off = 0.7
w1 = (bx - 0.8 * ux + side * off * nx, by - 0.8 * uy + side * off * ny)
w2 = (bx + 0.85 * ux + side * off * nx, by + 0.85 * uy + side * off * ny)
gx, gy = bx + 0.85 * ux, by + 0.85 * uy
api.go_to(w1[0], w1[1], max_speed=0.2)
api.go_to(w2[0], w2[1], max_speed=0.2)
api.go_to(gx, gy, max_speed=0.2)
api.go_to(gx, gy, math.atan2(by - gy, bx - gx), max_speed=0.2)
print("final", [round(v, 2) for v in api.get_robot_pose()])
