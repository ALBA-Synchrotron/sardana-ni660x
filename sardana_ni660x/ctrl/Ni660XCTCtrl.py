#!/usr/bin/env python
import numpy

import PyTango
import taurus

from sardana import State
from sardana.pool import AcqSynch
from sardana.pool.controller import (CounterTimerController, Memorize,
                                     Memorized, NotMemorized, Type, Access,
                                     DataAccess, Description, DefaultValue)
from sardana.sardanavalue import SardanaValue

from sardana_ni660x.utils import CONNECTTERMS_DOC, getPFINameFromFriendlyWords, ConnectTerms

ReadWrite = DataAccess.ReadWrite
ReadOnly = DataAccess.ReadOnly

CHANNELDEVNAMES_DOC = ('Comma separated Ni660XCounter Tango device names.',
                       ' First channel (configured with COPulseChanTime as'
                       ' applicationType) is used as a timer.'
                       ' Subsequent channels (configured with "input"'
                       ' application type e.g. CICountEdgesChan) are used'
                       ' as counters.')

class Ni660XCTCtrl(object):
    """This class is the Ni600X counter Sardana CounterTimerController.
    It can work in step and continuous scan mode. 
    
    This controller does not work with a measurement group with only a time element.
    """

    MaxDevice = 32
    # Using the 80MHz clock the maximum high time is 53.687091187s
    # It corresponds to 2^32-1 ticks of 12.5ns each
    max_time = 53.687091187
    # Using the 80MHz clock the minimum high time is 25ns
    # It corresponds to two ticks of 12.5ns each
    min_time = 25e-7

    ctrl_properties = {'channelDevNames': {Description: CHANNELDEVNAMES_DOC,
                                           Type: str},
                       'connectTerms': {Description: CONNECTTERMS_DOC,
                                        Type: str,
                                        DefaultValue: '{}'},
                       'latencyTime': {Description: 'Controller latency time',
                                       Type: float,
                                       DefaultValue: 25e-7}
                      }

    axis_attributes = {
        "channelDevName": {
            Type: str,
            Access: ReadOnly
        },
        "sampleClockSource": {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized
        },
    }

    # relation between state and status  
    state_to_status = {
        State.On: 'Device finished counting',
        State.Standby: 'Device is standby',
        State.Moving: 'Device is counting'
    }

    # buffer attribute name to be read in ReadOne
    # e.g. 'CountBuffer' or 'PositionBuffer'
    BUFFER_ATTR = None
    APP_TYPE = None
    SAMPLE_TIMING_TYPE = None
    CLK_SOURCE = None
    # every QUERY_FILTER calls to ReadOne, the real read to the device will
    # be executed
    QUERY_FILTER = 1
 
    direct_attributes = tuple()
    cached_attributes = ('sampleclocksource')

    def __init__(self, inst, props, *args, **kwargs):
        if self.BUFFER_ATTR is None:
            msg = '%s does not define BUFFER_ATTR' % self.__class__.__name__
            raise Exception(msg)
        self.channelDevNamesList = self.channelDevNames.split(",")
        self.dataBuff = {}
        self.channels = {}
        self.counterName = {}
        self.index = {}
        self.delay_counter = {}
        self.aborted = {}
        self.attributes = {}
        self._repetitions = 0
        self.state = State.Unknown
        self.status = ""
        self.ch_configured = {}
        self._latency_time = self.latencyTime
        self.current_ch_configured = 0
        self.connect_terms_util = ConnectTerms(self.connectTerms)

    def AddDevice(self, axis):
        channel_name = self.channelDevNamesList[axis-1]
        try:
            self.channels[axis] = taurus.Device(channel_name)
        except Exception as e:
            msg = 'Exception when it created the taurus devices: %s' % e
            self._log.error(msg)

        # check the current application type
        properties_names = ['applicationType','counterName', 'DeviceName']
        properties = self.channels[axis].get_property(properties_names)
        app_type = properties['applicationType'][0]


        counterName = properties['counterName'][0]
        deviceName = properties['DeviceName'][0]
        self.counterName[axis] = '/%s/%s' % (deviceName, counterName)
        self.index[axis] = 0
        self.aborted[axis] = False
        self.delay_counter[axis] = 0
        # For input channels, initialize cache.
        if axis != 1:
            if app_type != self.APP_TYPE:
                msg = 'ERROR, The channel %r has wrong application type, ' \
                      '%r != ' \
                      '%r' % (axis, app_type, self.APP_TYPE)
                self._log.error(msg)
            self.ch_configured[axis] = False
            self.attributes[axis] = {}
            for name in self.cached_attributes:
                self.attributes[axis][name] = None

    def DeleteDevice(self, axis):
        # For input channels, remove cache.
        if axis != 1:
            self.attributes.pop(axis)
            self.ch_configured.pop(axis)
        self.channels.pop(axis)
        if len(self.channels) == 0:
            self.connect_terms_util.delete_cards()

    def GetAxisExtraPar(self, axis, name):
        self._log.debug("GetAxisExtraPar(%d, %s) entering..." % (axis, name))
        name = name.lower()
        if axis == 1:
            raise Exception('Attribute %s is not foreseen for timer' % name)
        if name == "channeldevname":
            v = self.channelDevNamesList[axis-1]
        elif name in self.direct_attributes:
            channel = self.channels[axis]
            v = channel.read_attribute(name).value
        else:
            v = self.attributes[axis][name]
            if name in self.cached_attributes and v is None:
                channel = self.channels[axis]
                v = channel.read_attribute(name).value
        return v

    def SetAxisExtraPar(self, axis, name, value):
        self._log.debug("SetAxisExtraPar(%d, %s, %s) entering..." %
                        (axis, name, value))
        name = name.lower()
        if axis == 1:
            raise Exception('Attribute %s is not foreseen for timer')
        if name in self.direct_attributes:
            channel = self.channels[axis]
            if channel.State() != PyTango.DevState.STANDBY:
                channel.Stop()
            self.channels[axis].write_attribute(name, value)
        else:
            self.attributes[axis][name] = value
            if name in self.cached_attributes:
                self.ch_configured[axis] = False

    def StateOneSingle(self, axis):
        state = self.channels[axis].State()

        # Force State ON for Timer
        if axis == 1:
            state = State.On
            status = self.state_to_status[state]
            return state, status

        # RUNNING state translates directly to MOVING
        if state == PyTango.DevState.RUNNING:
            state = State.Moving
        # STANDBY state translates directly to ON
        elif state == PyTango.DevState.STANDBY:
            state = State.On
        # In case of ON state check if all the data were 
        # already read (by the ReadOne method) 
        # if yes, return ON, if data were not yet passed
        # return MOVING
        elif state == PyTango.DevState.ON:
            state = State.On
        status = self.state_to_status[state]
        return state, status

    def StateOneMultiple(self, axis):
        if axis != 1:
            state = self.channels[axis].State()
            # RUNNING state translates directly to MOVING
            if state == PyTango.DevState.RUNNING:
                state = State.Moving
            # STANDBY state translates directly to ON
            elif state == PyTango.DevState.STANDBY:
                state = State.On
            # In case of ON state check if all the data were 
            # already read (by the ReadOne method) 
            # if yes, return ON, if data were not yet passed
            # return MOVING
            elif state == PyTango.DevState.ON:
                if axis not in self.index:
                    # The State is called without started the acquisition it
                    # is possible on the measurement group read state
                    state = State.On
                else:
                    index = self.index[axis]
                    if index < self._repetitions:
                        state = State.Moving
                    else:
                        state = State.On
        else:
            # Simulate state machine of the timer, if all the data were
            # passed or the timer was aborted, return ON.
            # Otherwise return MOVING
            index = self.index[axis]
            if index < self._repetitions and not self.aborted[axis]:
                state = State.Moving
            else:
                state = State.On
        status = self.state_to_status[state]
        return state, status

    def StateOne(self, axis):
        #self._log.debug('StateOne(%d): Entering...' % axis)
        if self._synchronization == AcqSynch.SoftwareTrigger:
            state, status = self.StateOneSingle(axis)
        else:
            state, status = self.StateOneMultiple(axis)
        #self._log.debug('StateOne(%d): Returning (%s, %s)' %
        #                (axis, state, status))
        return state, status

    def PreStartAll(self):
        self._log.debug("PreStartAll(): Entering...")
        # Reset all the channel's Indexe
        self.index = {}
        # Apply connect terms
        self.connect_terms_util.apply_connect_terms()
        self._log.debug("PreStartAll(): Leaving...")
        return True

    def StartAll(self):
        pass

    def PreStartOne(self, axis, value):
        self._log.debug("PreStartOne(%d, %f): Entering..." % (axis, value))
        self.index[axis] = 0
        self.aborted[axis] = False
        self.delay_counter[axis] = 0
        if axis != 1:
            channel = self.channels[axis]
            if channel.State() != PyTango.DevState.STANDBY:
                channel.Stop()
            if self.ch_configured[axis] == False:
                attributes = self.attributes[axis]
                clk_src = attributes[self.CLK_SOURCE]
                if clk_src != None:
                    channel.write_attribute(self.CLK_SOURCE, clk_src)
                else:
                    raise Exception('Undefined %r attribute' %self.CLK_SOURCE)

                channel.write_attribute("SampleTimingType",
                                        self.SAMPLE_TIMING_TYPE)
                repetitions = self._repetitions

                # To configure the buffer with 2 points in a single
                # acquisition with hardware trigger in CICountEdgesChan case
                if self.APP_TYPE == 'CICountEdgesChan' and self._repetitions == 1:
                    repetitions = int(2)

                channel.write_attribute('SampPerChan', int(repetitions))

                #TODO: Improve, set DMA to firsts 4 devices
                #if self.current_ch_configured > 4:
                #    transfer = 'Interrupts'
                #    channel.write_attribute('DataTransferMechanism', transfer)

                transfer = 'Interrupts'
                channel.write_attribute('DataTransferMechanism', transfer)

                self.current_ch_configured += 1
        return True

    def StartOne(self, axis, value):
        #self._log.debug("StartOne(%d, %f): Entering..." % (axis, value))
        if (axis != 1 or self._synchronization == AcqSynch.SoftwareTrigger):
            channel = self.channels[axis]
            channel.start()
        #self._log.debug("StartOne(%d, %f): Leaving..." % (axis, value))

    def PreLoadOne(self, axis, value, repetitions, latency):
        #self._log.debug("PreLoadOne(%d, %f, %d, %f): Entering...",
        #                axis, value, repetitions, latency)
        #self._log.debug("PreLoadOne(%d, %f): Leaving...",
        #                axis, value, repetitions, latency)
        return True

    def LoadOne(self, axis, value, repetitions, latency):
        self._log.debug("LoadOne(%d, %f, %r, %f): Entering...", axis, value,
                        repetitions, latency)
        self._repetitions = repetitions
        self._integration_time = value
        self.current_ch_configured = 0
        if axis != 1:
            if self._synchronization in [AcqSynch.HardwareTrigger,
                                         AcqSynch.HardwareGate]:
                pass
            else:
                raise Exception('The master channel must be the first channel.')
      
        elif self._synchronization in [AcqSynch.SoftwareTrigger,
                                       AcqSynch.SoftwareGate]:
            high_time = value
            low_time = self._latency_time
            if high_time > self.max_time:
                max_integ_time = self.min_time + self.max_time
                msg = ("Integration time not supported. Max = %f" %
                       max_integ_time)
                raise Exception(msg)
            channel = self.channels[axis]
            if channel.State() != PyTango.DevState.STANDBY:
                channel.Stop()
            channel.write_attribute('SampleTimingType', 'Implicit')
            channel.write_attribute('SampPerChan', int(self._repetitions))
            channel.write_attribute('HighTime', high_time)
            channel.write_attribute('LowTime', low_time)

        #self._log.debug("LoadOne(%d, %f, %d, %f): Leaving...",
        #                axis, value, repetitions, latency)

    def AbortOne(self, axis):
        # In case of Software _synchronization Stop the timer as well
        if axis != 1 or self._synchronization == AcqSynch.SoftwareTrigger:
            channel = self.channels[axis]
            if channel.State() != PyTango.DevState.STANDBY:
                channel.Stop()
        self.aborted[axis] = True

    def _calculate(self, axis, data, index):
        return data[index:]
        
    def ReadOneSingle(self, axis):
        index = self.index[axis]
        #self._log.debug('ReadOne(%d) index = %d' % (axis, index))
        if axis == 1:
            data = [self._integration_time]
        else:
            data = numpy.array([0])
            self.delay_counter[axis] += 1
            self.delay_counter[axis] %= self.QUERY_FILTER
            if self.delay_counter[axis] == 0:
                try:
                    channel = self.channels[axis]
                    data = channel.read_attribute(self.BUFFER_ATTR).value
                    if data is None:
                        data = numpy.array([0])
                except Exception as e:
                    msg = ('ReadOne(%d): Exception while reading' +
                           ' buffer: %s' % (axis, e))
                    self._log.error(msg)
                if len(data) == 2:
                    index = 1
                    data = self._calculate(axis, data, index)
        # values coming from CountBuffer are of type DevULong cast it to float
        data = float(data[0])
        sardana_value = SardanaValue(data)
        #self._log.debug('ReadOne(%d): data: %s' % (axis, repr(data)))
        return sardana_value

    def ReadOneMultiple(self, axis):
        index = self.index[axis]
        self._log.debug('ReadOne(%d) index = %d' % (axis, index))
        if self.index[axis] == self._repetitions:
            # Return empty data
            return []

        if axis == 1:
            max_index = max(self.index.values())
            rep = max_index - index
            data = numpy.tile(self._integration_time, rep)
        else:
            data = numpy.array([])
            self.delay_counter[axis] += 1
            self.delay_counter[axis] %= self.QUERY_FILTER
            if self.delay_counter[axis] == 0:
                try:
                    channel = self.channels[axis]
                    data = channel.read_attribute(self.BUFFER_ATTR).value
                    if data is None:
                        data = numpy.array([])
                except Exception as e:
                    msg = ('ReadOne(%d): Exception while reading buffer: %s'
                           % (axis, e))
                    self._log.error(msg)
                if len(data) > 0:
                    data = self._calculate(axis, data, index)
        self.index[axis] = index + len(data)
        # Unused variable
        # idx = range(index, self.index[axis])
        data = data.tolist()
        return data

    def ReadOne(self, axis):
        #self._log.debug("ReadOne(%d): Entering...", axis)
        if self._synchronization == AcqSynch.SoftwareTrigger:
            ret = self.ReadOneSingle(axis)
        else:
            ret = self.ReadOneMultiple(axis)
        #self._log.debug('ReadOne(%d): Leaving....', axis)
        return ret

