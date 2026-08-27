import salabim as sim

#One clerk
"""
class CustomerGenerator(sim.Component): #generates customers with an inter arrival time of uniform dist from 5,15
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample()) #holds until the next customer


class Customer(sim.Component): #the customer
    def process(self):
        self.enter(waitingline) #customer places himself at the end of the line
        if clerk.ispassive(): #checks if the clerk is idle, then he activates him
            clerk.activate()
        self.passivate()


class Clerk(sim.Component): #clerk who serves the customers every 30 secs
    def process(self):
        while True:
            while len(waitingline) == 0:
                self.passivate()
            self.customer = waitingline.pop() #gets the first customer
            self.hold(30)
            self.customer.activate()


env = sim.Environment(trace=True)

CustomerGenerator()
clerk = Clerk()
waitingline = sim.Queue("waitingline")

env.run(till=50)
print()
waitingline.print_statistics()
"""

#Multiple clerks
""""
class CustomerGenerator(sim.Component): #generates customers with an inter arrival time of uniform dist from 5,15
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample()) #holds until the next customer


class Customer(sim.Component): #the customer
    def process(self):
        self.enter(waitingline) #customer places himself at the end of the line
        for clerk in clerks: #checks for each clerk
            if clerk.ispassive(): #checks if the clerk is idle, then he activates him
                clerk.activate()
                break #activates only one clerk
            self.passivate()


class Clerk(sim.Component): #clerk who serves the customers every 30 secs
    def process(self):
        while True:
            while len(waitingline) == 0:
                self.passivate()
            self.customer = waitingline.pop() #gets the first customer
            self.hold(30)
            self.customer.activate()


env = sim.Environment(trace=True)

CustomerGenerator()
clerks = [Clerk() for i in range(3)] #generates a list of 3 clerks
waitingline = sim.Queue("waitingline")

env.run(till=5000)

waitingline.print_histograms()
waitingline.print_info()
"""

#Using stores instead of queue
#IN A STORE WE CAN DEFINE A CAPACITY AND IF WE REQUEST SOMETHING OUTSIDE OF ITS CAPACITY
#IT STORES IT GOES INTO REQUESTING STATE. Here there is no limit

"""
import salabim as sim


class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            Customer().enter(waiting_room) #adds a customer
            self.hold(sim.Uniform(5, 15))


class Clerk(sim.Component):
    def process(self):
        while True:
            customer = self.from_store(waiting_room)
            self.hold(30)


class Customer(sim.Component):
     ... #no need to activate or passivate a clerk


env = sim.Environment(trace=False)
CustomerGenerator()
for _ in range(3):
    Clerk()
waiting_room = sim.Store("waiting_room")


env.run(till=5000)

waiting_room.print_statistics()
waiting_room.print_info()

"""

#using resources

"""
class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample())


class Customer(sim.Component):
    def process(self):
        self.request(clerks) #requests one of the clerks if available. Otherwise it sends in a request and waits
        self.hold(30) #unlike earlier, the customer itself holds himself for 30units
        self.release()  # not really required


env = sim.Environment(trace=False)
CustomerGenerator()
clerks = sim.Resource("clerks", capacity=3) #we define actually 1 clerk here with a capacity of 3 (acts like 3 clerks as the customer only requests 1)

env.run(till=5000)

clerks.print_statistics()
clerks.print_info()

"""

#Bank service with max queue line = 5 and renege (leaving) after 50 units

"""
class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample())


class Customer(sim.Component):
    def process(self):
        if len(waitingline) >= 5: #max waiting line = 5
            env.number_balked += 1
            env.print_trace("", "", "balked")
            print(env.now(), "balked",self.name())            
            self.cancel() #trashes the current customer
        self.enter(waitingline) #since self.cancel(), this will not do anything if trashed
        for clerk in clerks:
            if clerk.ispassive():
                clerk.activate()
                break  # activate only one clerk
        self.hold(50)  # if not serviced within this time, renege
        if self in waitingline: #checks after 50 units if the same self is still in the waiting line. If yes he hasnt been serviced
            self.leave(waitingline)
            env.number_reneged += 1
            env.print_trace("", "", "reneged")
        else:
            self.passivate()  # wait for service to be completed


class Clerk(sim.Component):
    def process(self):
        while True:
            while len(waitingline) == 0:
                self.passivate()
            self.customer = waitingline.pop()
            self.customer.activate()  # get the customer out of it's hold(50). This activates the customer to be serviced right now
            self.hold(30)
            self.customer.activate()  # signal the customer that's all's done. 


env = sim.Environment()
CustomerGenerator()
env.number_balked = 0
env.number_reneged = 0
clerks = [Clerk() for _ in range(3)]

waitingline = sim.Queue("waitingline")
env.run(duration=300000)
waitingline.length.print_histogram(30, 0, 1)
waitingline.length_of_stay.print_histogram(30, 0, 10)
print("number reneged", env.number_reneged)
print("number balked", env.number_balked)

"""



#Same problem using store: 

"""
class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            customer = Customer()
            self.to_store(waiting_room, customer, fail_at=env.now()) #tries to fit the customer in the store
            if self.failed():
                customer.cancel()
                env.number_balked += 1
                print(env.now(), "balked",customer.name())
                env.print_trace("", "", "balked",customer.name())
            self.hold(sim.Uniform(5, 15))


class Clerk(sim.Component):
    def process(self):
        while True:
            customer = self.from_store(waiting_room)
            self.hold(30)


class Customer(sim.Component):
    def process(self):
        self.hold(50)
        if self in waiting_room:
            self.leave(waiting_room)
            env.number_reneged += 1
            env.print_trace("", "", "reneged")

env = sim.Environment(trace=False)
env.number_balked = 0
env.number_reneged = 0
CustomerGenerator()
for _ in range(3):
    Clerk()
waiting_room = sim.Store("waiting_room", capacity=5)

env.run(till=30000)

waiting_room.length.print_histogram(30, 0, 1)
waiting_room.length_of_stay.print_histogram(30, 0, 10)
print("number reneged", env.number_reneged)
print("number balked", env.number_balked)

"""

#Using resources

"""
class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample())


class Customer(sim.Component):
    def process(self):
        if len(clerks.requesters()) >= 5: 
            env.number_balked += 1
            env.print_trace("", "", "balked")
            self.cancel()
        self.request(clerks, fail_delay=50) #request clerk. if not serviced within 50units it fails
        if self.failed():
            env.number_reneged += 1
            env.print_trace("", "", "reneged")
        else:
            self.hold(30)
            self.release()


env = sim.Environment()
CustomerGenerator()
env.number_balked = 0
env.number_reneged = 0
clerks = sim.Resource("clerks", 3)

env.run(till=50000)

clerks.requesters().length.print_histogram(30, 0, 1)
print()
clerks.requesters().length_of_stay.print_histogram(30, 0, 10)
print("number reneged", env.number_reneged)
print("number balked", env.number_balked)
"""


#Using State (No renenge and balking)

"""
class CustomerGenerator(sim.Component):
    def process(self):
        while True:
            Customer()
            self.hold(sim.Uniform(5, 15).sample())


class Customer(sim.Component):
    def process(self):
        self.enter(waitingline)
        worktodo.trigger(max=1) #triggers at max 1 clerk to do work
        self.passivate()


class Clerk(sim.Component):
    def process(self):
        while True:
            if len(waitingline) == 0:
                self.wait((worktodo, True, 1)) #this makes the clerk wait for worktodo
            self.customer = waitingline.pop()
            self.hold(30)
            self.customer.activate()


env = sim.Environment()
CustomerGenerator()
for i in range(3):
    Clerk()
waitingline = sim.Queue("waitingline")
worktodo = sim.State("worktodo") #initially set as False

env.run(till=50000)
waitingline.print_histograms()
worktodo.print_histograms()

"""

