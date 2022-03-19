#!/usr/bin/env python

from hardware import *
import log
#
## emulates a compiled program
class Program():

    def __init__(self, name, instructions):
        self._name = name
        self._instructions = self.expand(instructions)

    @property
    def name(self):
        return self._name

    @property
    def instructions(self):
        return self._instructions

    def addInstr(self, instruction):
        self._instructions.append(instruction)

    def expand(self, instructions):
        expanded = []
        for i in instructions:
            if isinstance(i, list):
                ## is a list of instructions
                expanded.extend(i)
            else:
                ## a single instr (a String)
                expanded.append(i)

        ## now test if last instruction is EXIT
        ## if not... add an EXIT as final instruction
        last = expanded[-1]
        if not ASM.isEXIT(last):
            expanded.append(INSTRUCTION_EXIT)

        return expanded

    def __repr__(self):
        return "Program({name}, {instructions})".format(name=self._name, instructions=self._instructions)


## emulates an Input/Output device controller (driver)
class IoDeviceController():

    def __init__(self, device):
        self._device = device
        self._waiting_queue = []
        self._currentPCB = None

    def runOperation(self, pcb, instruction):
        pair = {'pcb': pcb, 'instruction': instruction}
        # append: adds the element at the end of the queue
        self._waiting_queue.append(pair)
        # try to send the instruction to hardware's device (if is idle)
        self.__load_from_waiting_queue_if_apply()

    def getFinishedPCB(self):
        finishedPCB = self._currentPCB
        self._currentPCB = None
        self.__load_from_waiting_queue_if_apply()
        return finishedPCB

    def __load_from_waiting_queue_if_apply(self):
        if (len(self._waiting_queue) > 0) and self._device.is_idle:
            ## pop(): extracts (deletes and return) the first element in queue
            pair = self._waiting_queue.pop(0)
            #print(pair)
            pcb = pair['pcb']
            instruction = pair['instruction']
            self._currentPCB = pcb
            self._device.execute(instruction)

    def __repr__(self):
        return "IoDeviceController for {deviceID} running: {currentPCB} waiting: {waiting_queue}".format(deviceID=self._device.deviceId, currentPCB=self._currentPCB, waiting_queue=self._waiting_queue)


####################################################################################
##IMPLEMENTACION DE INTERRUPCIONES

## emulates the  Interruptions Handlers
class AbstractInterruptionHandler():
    def __init__(self, kernel):
        self._kernel = kernel

    @property
    def kernel(self):
        return self._kernel

    def execute(self, irq):
        log.logger.error("-- EXECUTE MUST BE OVERRIDEN in class {classname}".format(classname=self.__class__.__name__))

    def pcbInHandler(self,pcb):
        if self.kernel.pcbTable.runningPCB is None: ##si no tiene nada corriendo
            pcb.state = State.Running
            self.kernel.pcbTable.runningPCB = pcb
            self.kernel.dispatcher.load(pcb)
            log.logger.info("Now is running: {path}".format(path=pcb.path))
        else:
            pcbRunning = self.kernel.pcbTable.runningPCB ##si tiene algo corriendo

            if self.kernel.scheduler.aplicaExpropiacion(pcb,pcbRunning): ##y tengo scheduling expropiativo
                log.logger.info("CPU expropriation for: {path}".format(path=pcb.path))
                self.expropiativeContext(pcb,pcbRunning)

            else:
                pcb.state = State.Ready
                self.kernel.scheduler.enqueueProcess(pcb)


    def expropiativeContext(self,pcb,pcbRunning):
        pcbExpropiado = pcbRunning
        self.kernel.pcbTable.runningPCB = None
        pcbExpropiado.state = State.Ready
        self.kernel.dispatcher.save(pcbExpropiado)
        self.kernel.scheduler.enqueueProcess(pcbExpropiado)  ##encolamos el proceso actual en readyQueue
        self.kernel.dispatcher.load(pcb)
        pcb.state = State.Running
        self.kernel.pcbTable.runningPCB = pcb

    def pcbOutHandler(self):
        if not self.kernel.scheduler.readyQueue.isEmpty():
            nextPcb = self.kernel.scheduler.getNextProcess()
            nextPcb.state = State.Running
            self.kernel.pcbTable.runningPCB = nextPcb
            self.kernel.dispatcher.load(nextPcb)
            log.logger.info("Now is running: {path}".format(path=nextPcb.path))


class KillInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        pcb = self.kernel.pcbTable.runningPCB
        log.logger.info("Program Finished: {prg}".format(prg=pcb.path))
        self.kernel.memoryManager.free_frames_linked_to(pcb.pid)
        pcb.state = State.Terminated
        self.kernel.dispatcher.save(pcb)
        self.kernel.pcbTable.runningPCB = None
        #self.kernel.pcbTable.remove(pcb.pid)
        self.pcbOutHandler()

        if self.kernel.pcbTable.seQuedaSinProcesos():
            HARDWARE.switchOff()

class IoInInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        program = irq.parameters
        pcb = self.kernel.pcbTable.runningPCB
        self.kernel.pcbTable.runningPCB = None
        pcb.state = State.Waiting
        self.kernel.dispatcher.save(pcb)
        self.kernel.ioDeviceController.runOperation(pcb, program)
        log.logger.info(self.kernel.ioDeviceController)
        self.pcbOutHandler()

class IoOutInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        pcb = self.kernel.ioDeviceController.getFinishedPCB()
        log.logger.info(self.kernel.ioDeviceController)
        self.pcbInHandler(pcb)

class NewInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        path = irq.parameters[0]
        priority = irq.parameters[1]
        pid = self.kernel.pcbTable.nuevoPid
        pcb = Pcb(pid,0,0,path,priority)
        self.kernel.pcbTable.add(pcb)
        pages = self.kernel.loader.load(pcb)
        self.kernel.memoryManager.putPageTable(pcb.pid, pages)
        self.pcbInHandler(pcb)

#Se agrega producto del timer en el RoundRobinScheduler
class TimeoutInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        if not self.kernel.scheduler.isEmptyReadyQueue():
            runningPcb = self.kernel.pcbTable.runningPCB
            self.kernel.pcbTable.runningPCB = None
            runningPcb.state = State.Ready
            self.kernel.scheduler.enqueueProcess(runningPcb)
            self.kernel.dispatcher.save(runningPcb)
            self.pcbOutHandler()
        else:
            HARDWARE.timer.reset()

class StatInterruptionHandler(AbstractInterruptionHandler):
    def execute(self, irq):
        if not self.kernel.pcbTable.seQuedaSinProcesos():
            self.agigingReadyProcess(self.kernel.pcbTable.table)

    def agigingReadyProcess(self,pcbTable):
        for pcb in pcbTable :
            pcb.aging()

####################################################################################
## IMPEMENTACION DE SCHEDULING

class FIFOScheduler:
    def __init__(self):
        self._readyQueue = Queue()

    @property
    def readyQueue(self):
        return self._readyQueue

    def isEmptyReadyQueue(self):
        return self.readyQueue.isEmpty()

    def aplicaExpropiacion(self,pcbReady,pcbRunning):
        return False

class FCFSScheduler(FIFOScheduler):
    def enqueueProcess(self, proceso):
        self.readyQueue.agregarProceso(proceso)

    def getNextProcess(self):
        return self.readyQueue.getFirstProcess()


class RoundRobinScheduler(FIFOScheduler):
    def __init__(self,quantum):
        super(RoundRobinScheduler, self).__init__()
        HARDWARE.timer.quantum = quantum

    def enqueueProcess(self, proceso):
        self.readyQueue.agregarProceso(proceso)

    def getNextProcess(self):
        return self.readyQueue.getFirstProcess()

#------------------------------------#

class PriorityScheduler:
    def __init__(self):
        self._readyQueue = PriorityQueue()

    @property
    def readyQueue(self):
        return self._readyQueue

    def isEmptyReadyQueue(self):
        return self.readyQueue.isEmpty()

    def enqueueProcess(self, proceso):
        self.readyQueue.agregarProceso(proceso)

    def getNextProcess(self):
        return self.readyQueue.getFirstProcess()

class PriorityNoExpropiativeScheduler(PriorityScheduler):
    def aplicaExpropiacion(self,pcbReady,pcbRunning):
        return False

class PriorityExpropiativeScheduler(PriorityScheduler):
    def aplicaExpropiacion(self,pcbReady,pcbRunning):
        resultado = pcbReady.priorityAging < pcbRunning.priorityAging
        return resultado

########################################################################################################################
#MANEJO DE PROGRAM COUNTER

#emula la PCBTable
class PCBTable():
    def __init__(self):
        self._pidActual = 0
        self._pcbTable = []
        self.runningPCB = None

    def get(self, pid):
        return self._pcbTable[pid]

    def add(self, pcb):
        self._pcbTable.append(pcb)

    def remove(self, pid):
        new_list = []
        for pcb in self._pcbTable:
            if pcb.pid != pid:
                new_list.append(pcb)
        self._pcbTable = new_list

    @property
    def nuevoPid(self):
        valorARetornar = self._pidActual
        self._pidActual = self._pidActual + 1
        return valorARetornar

    @property
    def runningPCB(self):
        return self._runningPCB

    @runningPCB.setter
    def runningPCB(self, newRunningPCB):
        self._runningPCB = newRunningPCB

    @property
    def table(self):
        return self._pcbTable

    def seQuedaSinProcesos(self):
        result = True
        for pcb in self.table:
            result = result and pcb.state==State.Terminated
        return result

#Process Control Block
class Pcb():
    def __init__(self, pid, basedir, pc, path, priority):
        self._pid = pid
        self._baseDir = basedir
        self._pc = pc
        self._path = path
        self._state = State.Ready
        self._priority = priority       #viene del seteo del prg
        self._priorityAging = priority  ##la que se modifca
        self._readyTime = 0
        self._runningTime=0
        self._waitingTime=0
        self._inReadyTime=0

    @property
    def pid(self):
        return self._pid

    @property
    def baseDir(self):
        return self._baseDir

    @property
    def path(self):
        return self._path

    @property
    def pc(self):
        return self._pc

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, nuevoEstado):
        self._state = nuevoEstado

    @pc.setter
    def pc(self, pc):
        self._pc = pc

    @property
    def priority(self):
        return self._priority

    @property
    def readyTime(self):
        return self._readyTime

    @property
    def priorityAging(self):
        return self._priorityAging

    @readyTime.setter
    def readyTime(self, value):
        self._readyTime = value

    @priorityAging.setter
    def priorityAging(self, value):
        self._priorityAging = value

    def aging(self):
        if self.state==State.Ready:
            if self.readyTime<3:
                self.readyTime = self.readyTime+1
            else:
                self.readyTime = 0
                if self.priorityAging>1:
                    self.priorityAging = (self.priorityAging-1)
                    log.logger.info("AGING PRIORITY: {pcb}".format(pcb=self))
        else:
            self.priorityAging=self.priority
            self.readyTime = 0

    def __repr__(self):
        return "PCB(pid={}, baseDir={}, pc={}, state={}, path={}, priority={})".format(self.pid, self.baseDir, self.pc, self.state, self.path, self.priorityAging)

########################################################################################################################
class MemoryManager():
    def __init__(self, memory, frameSize):
        self._freeFrames = list(range(memory.size // frameSize))
        self._frameSize = frameSize
        self._pageTable = dict()
        self._memory = memory

    @property
    def freeFrames(self):
        return self._freeFrames

    ##obtiene la page table de un proceso en particular
    def getPageTable(self, pid):
        return self._pageTable.get(pid)

    def putPageTable(self, pid, pages):
        self._pageTable.update({pid: pages})

    def getFreeMemory(self):
        return len(self._freeFrames) * self._frameSize

    @property
    def memory(self):
        return self._memory

    def allocFrames(self, cantInstr):
        framesNeeded = cantInstr // self._frameSize
        if cantInstr % self._frameSize > 0:
            framesNeeded += 1

        if framesNeeded <= len(self._freeFrames):
            allocatedFrames = self._freeFrames[0:framesNeeded]
            self._freeFrames = self._freeFrames[framesNeeded:]
        else:
            allocatedFrames = []

        return allocatedFrames

    def free_frames_linked_to(self, pid):
        page_table = self._pageTable.get(pid)
        self._freeFrames.extend(page_table)

class FileSystem():

    def __init__(self):
        self._fileSystem = dict()

    def write(self, path, program):
        self._fileSystem.update({path:program})

    def read(self, path):
        return self._fileSystem.get(path)

########################################################################################################################
##El loader puede guardar el “próximo” lugar de inicio a guardar el programa
class Loader():
    def __init__(self, kernel):
        self._kernel = kernel
        self._memoryPos = 0

    @property
    def memoryPos(self):
        return self._memoryPos

    @memoryPos.setter
    def memoryPos(self, value):
        self._memoryPos = value

    def load(self, pcb):
        program = self._kernel.fileSystem.read(pcb.path)
        prgSize= len(program.instructions)
        frames = self._kernel.memoryManager.allocFrames(prgSize)
        frameSize= self._kernel.memoryManager._frameSize

        for dirInstr in range(0,prgSize):
            pageId = dirInstr // frameSize
            offset = dirInstr % frameSize
            frameId = frames[pageId]
            baseFrame = frameId * self._kernel.memoryManager._frameSize
            dirFisica = baseFrame + offset
            inst = program.instructions[dirInstr]
            self._kernel.memoryManager.memory.write(dirFisica,inst)
        return frames

class Dispatcher():
    def __init__(self, cpu, mmu,kernel):
        self._cpu = cpu
        self._mmu = mmu
        self._kernel = kernel

    def load(self, pcb):
        self._cpu.pc = pcb.pc
        self._mmu.baseDir = pcb.baseDir
        self._mmu.resetTLB()
        pages = self._kernel.memoryManager.getPageTable(pcb.pid)
        for p in range(0, len(pages)):
            self._mmu.setPageFrame(p,pages[p])
        HARDWARE.timer.reset()

    def save(self, pcb):
        pcb.pc = self._cpu.pc
        self._cpu.pc = -1
        log.logger.info("save pcb:{pcb}".format(pcb=pcb))

########################################################################################################################
# Estructuras de dato del tipo Queue
class Queue():
    def __init__(self):
        self._queue = []

    def agregarProceso(self, proceso):
        self._queue.append(proceso)

    def getFirstProcess(self):
        return self._queue.pop(0)

    def isEmpty(self):
        return len(self._queue) == 0


class PriorityQueue():
    def __init__(self):
        self._queue = []

    def agregarProceso(self, proceso):
        self._queue.append(proceso)

    def getFirstProcess(self):
        maxPriorityPcb = self._queue[0]
        currentMaxPriority= maxPriorityPcb.priorityAging
        for pcb in self._queue:
            #menor igual resuelve desempate por FIFO
            if pcb.priority <= currentMaxPriority:
                maxPriorityPcb = pcb
                currentMaxPriority = maxPriorityPcb.priorityAging
        self._queue.remove(maxPriorityPcb)
        return maxPriorityPcb

    def isEmpty(self):
            return len(self._queue) == 0

########################################################################################################################
class State():
    Running = "RUNNING"
    Ready = "READY"
    Waiting = "WAITING"
    Terminated = "TERMINATED"
########################################################################################################################
# emulates the core of an Operative System
class Kernel():
    def __init__(self, scheduler,frameSize):
        ## setup interruption handlers
        killHandler = KillInterruptionHandler(self)
        HARDWARE.interruptVector.register(KILL_INTERRUPTION_TYPE, killHandler)

        ioInHandler = IoInInterruptionHandler(self)
        HARDWARE.interruptVector.register(IO_IN_INTERRUPTION_TYPE, ioInHandler)

        ioOutHandler = IoOutInterruptionHandler(self)
        HARDWARE.interruptVector.register(IO_OUT_INTERRUPTION_TYPE, ioOutHandler)

        newHandler = NewInterruptionHandler(self)
        HARDWARE.interruptVector.register(NEW_INTERRUPTION_TYPE, newHandler)

        timeoutHandler = TimeoutInterruptionHandler(self)
        HARDWARE.interruptVector.register(TIMEOUT_INTERRUPTION_TYPE, timeoutHandler)

        statHandler = StatInterruptionHandler(self)
        HARDWARE.interruptVector.register(STAT_INTERRUPTION_TYPE,statHandler)

        ## controls the Hardware's I/O Device
        self._ioDeviceController = IoDeviceController(HARDWARE.ioDevice)

        ## driver for interaction with cpu and mmu
        self._dispatcher = Dispatcher(HARDWARE.cpu, HARDWARE.mmu,self)

        ##specific component to load programs in main memmory
        self._loader = Loader(self)

        ##helps kernel to keep process state
        self._pcbTable = PCBTable()

        #el algoritmo de scheduling se pasa por parametro en el init
        self._scheduler = scheduler
        #
        self._fileSystem = FileSystem()
        #
        HARDWARE.mmu.frameSize=frameSize
        self._memoryManager = MemoryManager(HARDWARE.memory, HARDWARE.mmu.frameSize)
        #

    @property
    def pcbTable(self):
        return self._pcbTable

    @property
    def loader(self):
        return self._loader

    @property
    def dispatcher(self):
        return self._dispatcher

    @property
    def scheduler(self):
        return self._scheduler

    @property
    def memoryManager(self):
        return self._memoryManager

    @property
    def fileSystem(self):
        return self._fileSystem

    @property
    def ioDeviceController(self):
        return self._ioDeviceController

    def load_program(self, program):
        return self._loader.load_program(program)

    ## emulates a "system call" for programs execution
    def run(self, path, priority):
        newIRQ = IRQ(NEW_INTERRUPTION_TYPE, (path,priority))
        HARDWARE._interruptVector.handle(newIRQ)
        log.logger.info("Executing program: {program} -> priority: {priority}".format(program=path, priority=priority))
        log.logger.info(HARDWARE)

    def __repr__(self):
        return "Kernel "

########################################################################################################################
########################################################################################################################
##  GANTT CHART
class GanttChart():
    def __init__(self, kernel):
        self._kernel = kernel
        self._repr = []
        self._headers = ["proceso"]

    def tick(self, ticknum):
        if ticknum == 1:    #armo template en el momento 1
             self._repr = self.doTemplate(self._kernel.pcbTable.table)
             self.update(ticknum, self._kernel.pcbTable.table)

        if ticknum > 1:     #siempre que haya ticks sigo actualizando
            self.update(ticknum, self._kernel.pcbTable.table)

        if self.allFinish() :
            log.logger.info(self.__repr__())
            self.calcularTiempos(ticknum)

    def update(self, nroTick, pcbTable):
        self._headers.append(nroTick)
        pnum = 0
        for pcb in pcbTable:
            if  pcb.state == State.Running:
                character = "R"
                pcb._runningTime = pcb._runningTime + 1
            if pcb.state == State.Waiting:
                character = "w"
                pcb._waitingTime = pcb._waitingTime + 1
            if pcb.state == State.Ready:
                character = "."
                pcb._inReadyTime = pcb._inReadyTime + 1
            if pcb.state == State.Terminated:
                character = " "
            self._repr[pnum].append(character)
            pnum = pnum + 1

    def doTemplate(self, pcbTable):
        lista = []
        for pcb in pcbTable:
            lista.append([pcb.path])
        return lista

    def allFinish(self):
        return self._kernel.pcbTable.seQuedaSinProcesos()

    def calcularTiempos(self,cantidadDeTicks):
        for pcb in self._kernel.pcbTable.table:
            log.logger.info("Proceso: {program} -> Tiempo de Respuesta: {rtaTime} -> Tiempo De Espera: {waitingTime} -> Tiempo en Cola de Ready: {readyTime}".format
                            (program=pcb.path, rtaTime=pcb._waitingTime+pcb._runningTime+pcb._inReadyTime, waitingTime=pcb._waitingTime, readyTime=pcb._inReadyTime))

    def __repr__(self):
        return tabulate(self._repr, headers=self._headers, tablefmt='grid', stralign='center')

