g = api.get_task_goal()
x,y,a = g["pose"]
bx,by,ba = api.get_object_pose(g["target"])
api.go_to(bx-.60,by,0,max_speed=0.2)
x = x-.50
api.go_to(x,y,a,max_speed=0.2)
