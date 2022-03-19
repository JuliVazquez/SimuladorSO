from hardware import *
from so import *
import log


##
##  MAIN 
##
if __name__ == '__main__':
    log.setupLogger()
    log.logger.info('Starting emulator')
    ## setup our hardware and set memory size
    HARDWARE.setup(32)
    HARDWARE.cpu.enable_stats = True

    ## Switch on computer
    opcion = None
    opcionQuantum=None
    log.logger.info("Seleccione scheduler: ")
    log.logger.info("   1) First Come-First Search (FCFS)")
    log.logger.info("   2) RoundRobin (quantum 3)")
    log.logger.info("   3) Priority con expropiacion")
    log.logger.info("   4) Priority sin expropiacion")

    while opcion is None:
        opcion = input()
        if opcion.isdigit():
            if not 1 <= int(opcion) <= 4:
                print("La ópcion no es válida, ingrese nuevamente")
                opcion = None
        else:
            print("La ópcion no es válida, ingrese nuevamente")
            opcion = None
    if opcion == "1":
        scheduler = FCFSScheduler()
        log.logger.info('Se utilizará FCFSScheduler')
    if opcion == "2":
        scheduler = RoundRobinScheduler(3)
        log.logger.info('Se utilizará RoundRobinScheduler con un quantum de 3')
    if opcion == "3":
        scheduler = PriorityExpropiativeScheduler()
        log.logger.info('Se utilizará PriorityExpropiativeScheduler')
    if opcion == "4":
        scheduler = PriorityNoExpropiativeScheduler()
        log.logger.info('Se utilizará PriorityNoExpropiativeScheduler')

    sleep(2)
    HARDWARE.switchOn()
    kernel = Kernel(scheduler,4)

    gantt = GanttChart(kernel)
    HARDWARE.clock.addSubscriber(gantt)


    # Ahora vamos a intentar ejecutar varios programas a la vez
    ##################
    prg1 = Program("prg1.exe", [ASM.CPU(2), ASM.IO(), ASM.CPU(3), ASM.IO(), ASM.CPU(2)])
    prg2 = Program("prg2.exe", [ASM.CPU(7)])
    prg3 = Program("prg3.exe", [ASM.CPU(4), ASM.IO(), ASM.CPU(1)])
    prg4 = Program("prg4.exe", [ASM.CPU(3)])

    prg5 = Program("prg5.exe", [ASM.CPU(2), ASM.IO(), ASM.CPU(1)])
    prg6 = Program("prg6.exe", [ASM.CPU(2)])
    prg7 = Program("prg7.exe", [ASM.CPU(2)])

    kernel.fileSystem.write("F:/prg5.exe", prg5)
    kernel.fileSystem.write("F:/prg6.exe", prg6)
    kernel.fileSystem.write("F:/prg7.exe", prg7)

    kernel.run("F:/prg5.exe",2)
    kernel.run("F:/prg6.exe",3)
    kernel.run("F:/prg7.exe",1)


