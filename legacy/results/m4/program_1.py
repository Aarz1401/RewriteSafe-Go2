x,y,a = api.get_object_pose("blue_box")
api.go_to(x-.7,y-.85,0,max_speed=.2)
api.go_to(x+.85,y-.85,0,max_speed=.2)
api.go_to(x+.85,y,pi,max_speed=0.2)
