from xml.sax.saxutils import escape

import mujoco


def build(task: dict) -> mujoco.MjModel:
    objects = []
    for obj in task["objects"]:
        name = escape(obj["name"])
        x, y, z = obj["pos"]
        sx, sy, sz = obj["size"]
        kind = obj.get("kind", "box")
        geom = "cylinder" if kind in ("person", "cone") else "box"
        size = f"{sx / 2} {sz / 2}" if geom == "cylinder" else f"{sx / 2} {sy / 2} {sz / 2}"
        joint = "<freejoint/>" if obj.get("dynamic", True) else ""
        color = obj.get("rgba", ".65 .45 .25 1")
        objects.append(
            f'<body name="{name}" pos="{x} {y} {z}">{joint}'
            f'<geom name="{name}" type="{geom}" size="{size}" mass="{obj["mass"]}" '
            f'rgba="{color}" friction=".6 .02 .002"/></body>'
        )
    gx, gy, _ = task["goal"]["pose"]
    # Only marked goals are drawn: other goals are defined relative to objects and must
    # not be visible in the top-down image a program can request.
    goal_alpha = ".4" if task["goal"].get("marker") else "0"
    xml = f'''<mujoco><option timestep="0.01" integrator="implicitfast"/>
    <visual><global offwidth="640" offheight="640"/></visual>
    <worldbody><light pos="0 0 5" dir="0 0 -1" directional="true" castshadow="false" diffuse=".8 .8 .8"/>
    <camera name="top" pos="0 0 6" quat="1 0 0 0" projection="orthographic" fovy="4.2"/>
    <geom name="floor" type="plane" size="2 2 .1" rgba=".16 .2 .23 1"/>
    <site name="goal" pos="{gx} {gy} .005" type="cylinder" size="{task["goal"].get("radius", 0.12)} .003" rgba=".1 .9 .5 {goal_alpha}"/>
    <body name="robot" pos="0 0 .22">
    <joint name="x" type="slide" axis="1 0 0" damping="0"/>
    <joint name="y" type="slide" axis="0 1 0" damping="0"/>
    <joint name="yaw" type="hinge" axis="0 0 1" damping="0"/>
    <geom name="robot" type="box" pos="0 0 .05" size=".35 .215 .15" mass="18" rgba=".12 .65 .8 1" friction=".3 .005 .0001" priority="1"/>
    <site pos=".30 0 .21" size=".04" rgba="1 1 1 1"/>
    </body>{"".join(objects)}</worldbody></mujoco>'''
    return mujoco.MjModel.from_xml_string(xml)
