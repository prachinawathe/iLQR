import numpy as np
from numpy import sin, cos
from numpy import linalg as LA
from pydrake.forwarddiff import jacobian
from pydrake.all import LinearQuadraticRegulator
from pydrake.systems.framework import VectorSystem
import matplotlib.pyplot as plt
# for meshcat
import time
import meshcat
import meshcat.geometry as geometry
import meshcat.transformations as tf

'''
x = [q, q_dot]
q = [x,y,z, phi(roll), theta(pitch), psi(yaw)]
[x,y,z]: position of quadrotor CG in world frame.
[r, p, y]: 321 rotation (same as Drake's RollPitchYaw class and
  the Mechanics of Flight textbook by Phillips)

Body frame and propeller numbering. Body z-axis points towards you.

       1       0
        \  x  /
         \ | /
      y___\|/
          / \
         /   \
        /     \
       2       3

Define constants kF and kM.
u[i]*kF (kM) is the force (torque) generated by propeller i.
'''
kF = 1.0
kM = 0.0245
l = 0.175/np.sqrt(2.0) # (length of one arm) / sqrt(2)
n = 12 # 12 states
m = 4 # 4 inputs
# intertial and gravitational constants
mass = 0.5
I = np.array([[0.0023, 0, 0],
              [0, 0.0023, 0],
              [0, 0, 0.0040]])
g = 9.8


def CalcRx(phi):
    c = cos(phi)
    s = sin(phi)
    Rx = np.array([[1., 0., 0.],
                   [0, c, -s],
                   [0, s, c]])
    return Rx


def CalcRy(theta):
    c = cos(theta)
    s = sin(theta)
    Ry = np.array([[c, 0., s],
                   [0, 1., 0],
                   [-s, 0., c]])
    return Ry


def CalcRz(psi):
    c = cos(psi)
    s = sin(psi)
    Rz = np.array([[c, -s, 0],
                   [s, c, 0],
                   [0., 0., 1]])
    return Rz


# Transformation matrix from Body frame to World frame.
def CalcR_WB(rpy):
    phi = rpy[0] # roll angle
    theta = rpy[1] # pitch angle
    psi = rpy[2] # yaw angle

    return CalcRz(psi).dot(CalcRy(theta).dot(CalcRx(phi)))


'''
pqr = Phi_inv * rpy_d
pqr is the angular velocity expressed in Body frame.
'''
def CalcPhiInv(rpy):
    roll = rpy[0]
    pitch = rpy[1]
    sr = sin(roll)
    cr = cos(roll)
    sp = sin(pitch)
    cp = cos(pitch)

    Phi = np.array([[1, 0, -sp],
                    [0, cr, sr*cp],
                    [0, -sr, cr*cp]])
    return Phi


'''
rpy_d = Phi * pqr
pqr is the angular velocity expressed in Body frame.
'''
def CalcPhi(rpy):
    roll = rpy[0]
    pitch = rpy[1]
    sr = sin(roll)
    cr = cos(roll)
    sp = sin(pitch)
    cp = cos(pitch)

    Phi = np.array([[1, sr*sp/cp, cr*sp/cp],
                    [0, cr, -sr],
                    [0, sr/cp, cr/cp]])
    return Phi


def CalcPhiD(rpy):
    roll = rpy[0]
    pitch = rpy[1]
    sr = sin(roll)
    cr = cos(roll)
    sp = sin(pitch)
    cp = cos(pitch)
    cp2 = cp**2
    tp = sp/cp

    Phi_D = np.empty((3,3,3), dtype=object)
    Phi_D[:,0,:] = 0.0
    Phi_D[0, 1] = [cr * tp, sr / cp2, 0]
    Phi_D[0, 2] = [-sr * tp, cr / cp2, 0]
    Phi_D[1, 1] = [-sr, 0, 0]
    Phi_D[1, 2] = [-cr, 0, 0]
    Phi_D[2, 1] = [cr/cp, sr*sp/cp2, 0]
    Phi_D[2, 2] = [-sr/cp, cr*sp/cp2, 0]

    return Phi_D


# t is a 1D numpy array of time. The quadrotor has state x[i] at time t[i].
# wpts has shape (N, 3), where wpts[i] is the Cartesian coordinate of waypoint i.
def PlotTrajectoryMeshcat(x, t, vis, wpts_list = None):
    # initialize
    vis.delete()

    # plot waypoints
    if not(wpts_list is None):
        for i, wpts in enumerate(wpts_list):
            vis["wpt_%d" % i].set_object(geometry.Sphere(0.03),
                                         geometry.MeshLambertMaterial(color=0xffff00))
            T_wp = tf.translation_matrix(wpts)
            vis["wpt_%d" % i].set_transform(T_wp)


    d_prop = 0.10 # propeller diameter
    vis["quad"]["CG"].set_object(geometry.Sphere(0.03),
                                     geometry.MeshLambertMaterial(color=0x00ffff))
    vis["quad"]["body"].set_object(geometry.Box([0.2, 0.1, 0.1]),
                                   geometry.MeshLambertMaterial(color=0x404040))
    vis["quad"]["prop0"].set_object(geometry.Cylinder(0.01, d_prop),
                                    geometry.MeshLambertMaterial(color=0x00ff00))
    vis["quad"]["prop1"].set_object(geometry.Cylinder(0.01, d_prop),
                                    geometry.MeshLambertMaterial(color=0xff0000))
    vis["quad"]["prop2"].set_object(geometry.Cylinder(0.01, d_prop),
                                    geometry.MeshLambertMaterial(color=0xffffff))
    vis["quad"]["prop3"].set_object(geometry.Cylinder(0.01, d_prop),
                                    geometry.MeshLambertMaterial(color=0xffffff))

    Rx_prop = CalcRx(np.pi/2)
    TB = tf.translation_matrix([0,0,-0.05])
    T0 = tf.translation_matrix([l, -l, 0])
    T1 = tf.translation_matrix([l, l, 0])
    T2 = tf.translation_matrix([-l, l, 0])
    T3 = tf.translation_matrix([-l, -l, 0])
    T0[0:3,0:3] = Rx_prop
    T1[0:3,0:3] = Rx_prop
    T2[0:3,0:3] = Rx_prop
    T3[0:3,0:3] = Rx_prop

    vis["quad"]["body"].set_transform(TB)
    vis["quad"]["prop0"].set_transform(T0)
    vis["quad"]["prop1"].set_transform(T1)
    vis["quad"]["prop2"].set_transform(T2)
    vis["quad"]["prop3"].set_transform(T3)

    # visualize trajectory
    time.sleep(1.0)
    N = len(x)
    if not (t is None):
        assert N == len(t)

    for i, xi in enumerate(x):
        xyz = xi[0:3]
        rpy = xi[3:6]
        R_WB = CalcR_WB(rpy)
        T = tf.translation_matrix(xyz)
        T[0:3,0:3] = R_WB
        vis["quad"].set_transform(T)
        if i < N-1  and not(t is None):
            dt = t[i+1] - t[i]
        time.sleep(dt)

# define dynamics in a separate function, so that it can be passed to
# ForwardDiff.jacobian for derivatives.
def CalcF(x_u):
    x = x_u[0:n]
    u = x_u[n:n+m]
    xdot = np.empty(x.shape, dtype=object)

    I_inv = LA.inv(I)
    uF = kF * u
    uM = kM * u
    Fg = np.array([0., 0., -mass*g])
    F = np.array([0., 0., uF.sum()])
    M = np.array([l*(-uF[0] - uF[1] + uF[2] + uF[3]),
                  l*(-uF[0] - uF[3] + uF[1] + uF[2]),
                  - uM[0] + uM[1] - uM[2] + uM[3]])

    rpy = x[3:6]
    rpy_d = x[9:12]
    R_WB = CalcR_WB(rpy)

    # translational acceleration in world frame
    xyz_dd = 1./mass*(R_WB.dot(F) + Fg)

    # pqr: angular velocity in body frame
    Phi_inv = CalcPhiInv(rpy)
    pqr = Phi_inv.dot(rpy_d)
    pqr_d = I_inv.dot(M - np.cross(pqr, I.dot(pqr)))

    '''
    rpy_d = Phi * pqr ==>
    rpy_dd = Phi_d * pqr + Phi * pqr_d
    Phi_d.size = (3,3,3): Phi_d[i,j] is the partial of Phi[i,j]
        w.r.t rpy.
    '''
    Phi_d = CalcPhiD(rpy)
    Phi = CalcPhi(rpy)
    rpy_dd = Phi.dot(pqr_d) + (Phi_d.dot(rpy_d)).dot(pqr)

    xdot[0:6] = x[6:12]
    xdot[6:9] = xyz_dd
    xdot[9:12] = rpy_dd
    return xdot

def PlotTraj(x, dt = None, xw_list = None, t = None):
    x = x.copy() # removes reference to input variable.
    # add one dimension to x if x is 2D.
    if len(x.shape) == 2:
        x.resize(1, x.shape[0], x.shape[1])

    if t is None:
        N = x.shape[1]-1
        t = dt*np.arange(N+1)
    Ni = x.shape[0]

    fig = plt.figure(figsize=(15,12), dpi = 100)

    ax_x = fig.add_subplot(321)
    ax_x.set_ylabel("x rate")
    ax_x.axhline(color='r', ls='--')

    ax_y = fig.add_subplot(322)
    ax_y.set_ylabel("y rate")
    ax_y.axhline(color='r', ls='--')

    ax_z = fig.add_subplot(323)
    ax_z.set_ylabel("z rate")
    ax_z.axhline(color='r', ls='--')

    ax_roll = fig.add_subplot(324)
    ax_roll.set_ylabel("roll(phi) rate")
    ax_roll.set_xlabel("t")
    ax_roll.axhline(color='r', ls='--')

    ax_pitch = fig.add_subplot(325)
    ax_pitch.set_ylabel("pitch(theta) rate")
    ax_pitch.set_xlabel("t")
    ax_pitch.axhline(color='r', ls='--')

    ax_yaw = fig.add_subplot(326)
    ax_yaw.set_ylabel("yaw(psi) rate")
    ax_yaw.set_xlabel("t")
    ax_yaw.axhline(color='r', ls='--')

    for j in range(Ni):
        ax_x.plot(t, x[j,:,0])
        ax_y.plot(t, x[j,:,1])
        ax_z.plot(t, x[j,:,2])
        ax_roll.plot(t, x[j,:,3])
        ax_pitch.plot(t, x[j,:,4])
        ax_yaw.plot(t, x[j,:,5])

    # plot waypoints
    if not(xw_list is None):
        for xw in xw_list:
            ax_x.plot(xw.t, xw.x[0], 'r*')
            ax_y.plot(xw.t, xw.x[1], 'r*')
            ax_z.plot(xw.t, xw.x[2], 'r*')
            ax_roll.plot(xw.t, xw.x[3], 'r*')
            ax_pitch.plot(xw.t, xw.x[4], 'r*')
            ax_yaw.plot(xw.t, xw.x[5], 'r*')

    plt.show()


# Defines a drake vector system for the quadrotor.
class Quadrotor(VectorSystem):
    def __init__(self):
        VectorSystem.__init__(self,
            m,                           # No. of inputs.
            n)                           # No. of output.
        self.DeclareContinuousState(n) #OMKAR REMOVED UNDERSCORE
#        self._DeclarePeriodicPublish(0.005)

    # define dynamics in a separate function, so that it can be passed to
    # ForwardDiff.jacobian for derivatives.
    def f(self, x_u):
        return CalcF(x_u)

    # xdot(t) = -x(t) + x^3(t)
    def _DoCalcVectorTimeDerivatives(self, context, u, x, xdot):
        x_u = np.hstack((x.flatten(), u.flatten()))
        xdot[:] = self.f(x_u)

    # y(t) = x(t)
    def _DoCalcVectorOutput(self, context, u, x, y):
        y[:] = x

    ### copied from Greg's pset code. (set1, custom_pendulum.py, line67-79)
    # The Drake simulation backend is very careful to avoid
    # algebraic loops when systems are connected in feedback.
    # This system does not feed its inputs directly to its
    # outputs (the output is only a function of the state),
    # so we can safely tell the simulator that we don't have
    # any direct feedthrough.
    def _DoHasDirectFeedthrough(self, input_port, output_port):
        if input_port == 0 and output_port == 0:
            return False
        else:
            # For other combinations of i/o, we will return
            # "None", i.e. "I don't know."
            return None


if __name__ == '__main__':
    # simulate quadrotor w/ LQR controller using forward Euler integration.
    # fixed point
    xd = np.zeros(n)
    #xd[0:2] = [0,0]
    xd[2] = 3
    ud = np.zeros(m)
    ud[:] = mass * g / 4
    x_u = np.hstack((xd, ud))
    partials = jacobian(CalcF, x_u)
    A0 = partials[:, 0:n]
    B0 = partials[:, n:n+m]
    Q = 10*np.eye(n)
    R = np.eye(m)

    # get LQR controller about the fixed point
    K0, S0 = LinearQuadraticRegulator(A0, B0, Q, R)

    # simulate stabilizing about fixed point using LQR controller
    dt = 0.001
    N = int(4.0/dt)
    x = np.zeros((2*N+1, n))

    x0 = np.zeros(n)
    x[0] = x0

    timeVec = np.zeros(2*N+1)

    for i in range(N):
        x_u = np.hstack((x[i], -K0.dot(x[i]-xd) + ud))
        x[i+1] = x[i] + dt*CalcF(x_u)
        print(-K0.dot(x[i]-xd) + ud)
        timeVec[i] = timeVec[i-1] + dt

    # make a prop fail, see how various values change


    for i in range(int(N/8)):
        u_i = -K0.dot(x[i+N]-xd) + ud
        u_i[3] = 0
        # u_i[1] = 0  # uncomment this line to run two rotor failure
        x_u = np.hstack((x[i+N], u_i))
        x[i+N+1] = x[i+N] + dt*CalcF(x_u)
        print(u_i)
        timeVec[i+N] = timeVec[i+N-1] + dt

    PlotTraj(x[:,6:n], dt)
    #%% open meshact
    # vis = meshcat.Visualizer()
    # vis.open

    #%% Meshcat animation
    # PlotTrajectoryMeshcat(x, timeVec, vis)
