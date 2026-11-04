g = api.get_task_goal()
x,y,a = g["pose"]
bx,by,ba = api.get_object_pose("blue_box")
api.go_to(bx-.7,by-.85,0,max_speed=.2)
api.go_to(x,by-.85,0,max_speed=.2)
api.go_to(x,y,a,max_speed=0.2)
