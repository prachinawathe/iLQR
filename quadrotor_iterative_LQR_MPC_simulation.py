import numpy as np
from pydrake.all import (DiagramBuilder, SignalLogger, Simulator, PortDataType,
                         LinearQuadraticRegulator, BasicVector)
from pydrake.systems.framework import LeafSystem
from pydrake.forwarddiff import jacobian
from quadrotor3D import (Quadrotor, n, m, mass, g, CalcF, PlotTraj, PlotTrajectoryMeshcat)
from iLQR import WayPoint, TrajectorySpecs
from ilqr_quadrotor_3D import planner
# visualization
import matplotlib.pyplot as plt
import meshcat

#%% trajectory specifications
h = 0.01 # time step.
N = 100 # horizon
x0 = np.zeros(n)
u0 = np.zeros(m)
u0[:] = mass * g / 4

# desired fixed point
xd = np.zeros(n)
xd[0:3] = [2.,1, 1]
ud = np.zeros(m)
ud[:] = u0

# costs
QN = 100*np.diag([10,10,10,1,1,1,  0.1,0.1,0.1,0.1,0.1,0.1])
Q_vec = np.ones(n)
Q_vec[6:12] *= 0.1
Q = np.diag(Q_vec)# lqr cost
R = np.eye(m) # lqr cost

# waypoints
x1 = np.zeros(n)
x1[0:3] = [1, 0, 0.5]
t1 = 1.0
W1 = np.zeros(n)
W1_vec = np.zeros(n)
W1_vec[0:2] = 1
W1_vec[2] = 0.1
W1 = 10*np.diag(W1_vec)
rho1 = 5
xw = WayPoint(x1, t1, W1, rho1)

traj_specs = TrajectorySpecs(x0, u0, xd, ud, h, N, Q, R, QN, xw_list=[xw])
#%% Build drake diagram system and simulate.
builder = DiagramBuilder()
quad = builder.AddSystem(Quadrotor())

# controller system: applies iLQR controller to the quadcopter
class QuadIlqrMpcController(LeafSystem):
    def __init__(self):
        LeafSystem.__init__(self)
        self.DeclareInputPort(PortDataType.kVectorValued, n)
        self.DeclareVectorOutputPort(BasicVector(m), self._DoCalcVectorOutput)
        self.DeclareDiscreteState(m) # state of the controller system is u
        self.DeclarePeriodicDiscreteUpdate(period_sec=traj_specs.h) # update u every h seconds.
        self.is_plan_computed = False

    # u(t) = -K.dot(x(t)) ==> y(t) = -K.dot(u)
    def ComputeControlInput(self, x, u, t):
        traj_specs.x0[:] = x 
        traj_specs.u0[:] = u
        x_nominal, u_nominal, J, QN, Vx, Vxx, k, K = \
            planner.CalcTrajectory(traj_specs, t, is_logging_trajectories=False)
        u_next = u_nominal[0]
        print("simulation time:", t)
        return u_next


    def _DoCalcDiscreteVariableUpdates(self, context, events, discrete_state):
        # Call base method to ensure we do not get recursion.
        LeafSystem._DoCalcDiscreteVariableUpdates(self, context, events, discrete_state)

        control_input_reference = discrete_state.get_mutable_vector().get_mutable_value()
        x = self.EvalVectorInput(context, 0).get_value()
        u = control_input_reference.copy()
        new_u = self.ComputeControlInput(x, u, context.get_time())
        control_input_reference[:] = new_u


    def _DoCalcVectorOutput(self, context, y_basic_vector):
        control_output = context.get_discrete_state_vector().get_value()
        y = y_basic_vector.get_mutable_value()
        y[:] = control_output


# Create a simple block diagram containing our system.
controller = builder.AddSystem(QuadIlqrMpcController())
logger_x = builder.AddSystem(SignalLogger(n))
logger_u = builder.AddSystem(SignalLogger(m))

builder.Connect(controller.get_output_port(0), quad.get_input_port(0))
builder.Connect(quad.get_output_port(0), logger_x.get_input_port(0))
builder.Connect(quad.get_output_port(0), controller.get_input_port(0))
builder.Connect(controller.get_output_port(0), logger_u.get_input_port(0))
diagram = builder.Build()

# Create the simulator.
simulator = Simulator(diagram)

# if __name__ == '__main__':
# Set the initial conditions, x(0).
state = simulator.get_mutable_context().get_mutable_continuous_state_vector()
state.SetFromVector(traj_specs.x0)
input_vector = simulator.get_mutable_context().get_mutable_discrete_state_vector()
input_vector.SetFromVector(traj_specs.u0)
#%% Simulate
simulator.StepTo(h*300)

#%% plot
PlotTraj(logger_x.data().T, dt=None, xw_list=traj_specs.xw_list, t=logger_x.sample_times())
    
#%% open meshcat 
vis = meshcat.Visualizer()
vis.open()

#%% meshcat animation
wpts_list = np.zeros((len(traj_specs.xw_list)+1, 3))
for i, xw in enumerate(traj_specs.xw_list):
    wpts_list[i] = xw.x[0:3]
wpts_list[-1] = traj_specs.xd[0:3]

PlotTrajectoryMeshcat(logger_x.data().T, logger_x.sample_times(), vis, wpts_list)
