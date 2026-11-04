g = api.get_task_goal()
x,y,a = g["pose"]
api.go_to(x,y,a,max_speed=0.2)
