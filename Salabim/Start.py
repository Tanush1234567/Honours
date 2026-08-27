import salabim as sim

class Car(sim.Component):
    def process(self): 
        while True: 
            self.hold(1) #holds the process and schedules to come back to this after a second

env = sim.Environment(trace= True)
Car()
env.run(till=5)