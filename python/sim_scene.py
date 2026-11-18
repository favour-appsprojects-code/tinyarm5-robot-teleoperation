"""Simulated pick-and-place props for MuJoCo: cube, cup, gripper indicator, timer.

The TinyARM-5 URDF has no gripper finger joints and contact is disabled, so
grasping is simulated kinematically: closing the gripper while the tool tip is
within GRASP_RADIUS of the cube attaches it; opening releases it and it falls
onto the table or into the cup. This validates task flow and timing, not
contact physics or grasp robustness on the real gripper.
"""
import math
import mujoco
import numpy as np

CUBE_SIZE = 0.025
CUBE_START = (0.08, -0.17, CUBE_SIZE / 2)
CUP_CENTER = (-0.09, -0.17, 0.0)
CUP_RADIUS = 0.035      # inner radius, metres
CUP_HEIGHT = 0.06
CUP_FLOOR = 0.004
GRASP_RADIUS = 0.025
GRAVITY = 9.81
COLORS = dict(open=[0.1, 0.85, 0.2, 1], closed=[0.95, 0.15, 0.1, 1], none=[0.6, 0.6, 0.6, 1])


def add_pick_place(spec):
    """Add visual-only props (group 2, no contact) before spec.compile()."""
    box, cyl, sph = mujoco.mjtGeom.mjGEOM_BOX, mujoco.mjtGeom.mjGEOM_CYLINDER, mujoco.mjtGeom.mjGEOM_SPHERE
    world = spec.worldbody
    world.add_geom(name='table', type=box, size=[0.25, 0.2, 0.001], pos=[0, -0.15, -0.001],
                   rgba=[0.75, 0.72, 0.65, 1], contype=0, conaffinity=0, group=2)
    cube = world.add_body(name='cube', mocap=True, pos=list(CUBE_START))
    cube.add_geom(name='cube_geom', type=box, size=[CUBE_SIZE/2]*3, rgba=[0.9, 0.2, 0.2, 1],
                  contype=0, conaffinity=0, group=2)
    cup = world.add_body(name='cup', pos=list(CUP_CENTER))
    cup.add_geom(name='cup_floor', type=cyl, size=[CUP_RADIUS+0.003, CUP_FLOOR/2], pos=[0, 0, CUP_FLOOR/2],
                 rgba=[0.2, 0.4, 0.9, 1], contype=0, conaffinity=0, group=2)
    walls = 16
    for i in range(walls):
        angle = 2*math.pi*i/walls
        cup.add_geom(name=f'cup_wall_{i}', type=box,
                     size=[0.0025, CUP_RADIUS*math.tan(math.pi/walls)+0.001, CUP_HEIGHT/2],
                     pos=[(CUP_RADIUS+0.0025)*math.cos(angle), (CUP_RADIUS+0.0025)*math.sin(angle), CUP_HEIGHT/2],
                     euler=[0, 0, angle], rgba=[0.2, 0.4, 0.9, 0.55], contype=0, conaffinity=0, group=2)
    spec.body('rotor_4').add_geom(name='gripper_indicator', type=sph, size=[0.007, 0, 0],
                                  pos=[0, -0.01, 0.09], rgba=COLORS['none'], contype=0,
                                  conaffinity=0, group=2, mass=0)


class PickPlaceSim:
    def __init__(self, model, data, clock=None):
        self.model, self.data = model, data
        self.cube_mocap = model.body_mocapid[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'cube')]
        self.indicator = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, 'gripper_indicator')
        self.reset()

    def reset(self):
        self.cube = np.array(CUBE_START, dtype=float)
        self.velocity_z = 0.0
        self.grasped = False
        self.offset = np.zeros(3)
        self.was_closed = False
        self.elapsed = 0.0
        self.timer_running = False
        self.completed = False
        self.completed_time = None
        self.just_completed = False
        self._write()

    def _rest_height(self):
        horizontal = math.dist(self.cube[:2], CUP_CENTER[:2])
        if horizontal < CUP_RADIUS:
            return CUP_FLOOR + CUBE_SIZE/2
        return CUBE_SIZE/2

    def in_cup(self):
        horizontal = math.dist(self.cube[:2], CUP_CENTER[:2])
        return (not self.grasped and horizontal < CUP_RADIUS - CUBE_SIZE/4
                and self.cube[2] <= CUP_FLOOR + CUBE_SIZE/2 + 1e-4)

    def step(self, dt, tip, gripper, user_active):
        """Advance one control period. gripper is 'open', 'closed' or None."""
        tip = np.asarray(tip, dtype=float)
        closed = gripper == 'closed'
        self.just_completed = False
        if user_active and not self.timer_running and not self.completed:
            self.timer_running = True
        if self.timer_running:
            self.elapsed += dt
        if closed and not self.was_closed and not self.grasped:
            # Grasp only on the closing edge near the cube; sweeping a closed
            # gripper through the cube does not pick it up.
            if np.linalg.norm(self.cube - tip) <= GRASP_RADIUS:
                self.grasped = True
                self.offset = self.cube - tip
                self.velocity_z = 0.0
        if self.grasped and not closed:
            self.grasped = False
        self.was_closed = closed
        if self.grasped:
            self.cube = tip + self.offset
        else:
            rest = self._rest_height()
            if self.cube[2] > rest:
                self.velocity_z -= GRAVITY*dt
                self.cube[2] = max(rest, self.cube[2] + self.velocity_z*dt)
            if self.cube[2] <= rest:
                self.cube[2], self.velocity_z = rest, 0.0
        if self.timer_running and self.in_cup():
            self.timer_running = False
            self.completed = True
            self.completed_time = self.elapsed
            self.just_completed = True
        self._write(gripper)

    def _write(self, gripper=None):
        self.data.mocap_pos[self.cube_mocap] = self.cube
        self.model.geom_rgba[self.indicator] = COLORS.get(gripper or 'none', COLORS['none'])

    def state(self):
        return dict(cube_position=[round(float(v), 5) for v in self.cube],
                    cup_position=list(CUP_CENTER), cup_radius=CUP_RADIUS, cup_height=CUP_HEIGHT,
                    cube_size=CUBE_SIZE, cube_grasped=self.grasped, cube_in_cup=self.in_cup(),
                    task_elapsed_s=round(self.elapsed, 2), task_running=self.timer_running,
                    task_completed=self.completed)
