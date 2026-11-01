import math
sx, sy, _ = api.get_robot_pose()
bx, by, _ = api.get_object_pose("blue_box")
d = math.hypot(bx - sx, by - sy)
ux, uy = (bx - sx) / d, (by - sy) / d
gx, gy = bx + 0.85 * ux, by + 0.85 * uy
api.go_to(gx, gy, math.atan2(by - gy, bx - gx), max_speed=0.5)
print("goal", round(gx, 2), round(gy, 2), "final", [round(v, 2) for v in api.get_robot_pose()])
