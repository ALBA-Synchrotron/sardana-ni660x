import PyTango
from sardana import State
from sardana.pool.pooldefs import SynchDomain, SynchParam
from sardana.pool.controller import (TriggerGateController, Type, Description,
                                     DefaultValue, Access, DataAccess, Memorize, 
                                     Memorized, NotMemorized)

from sardana.tango.core.util import from_tango_state_to_state

from sardana_ni660x.utils import IdleState
from sardana_ni660x.utils import CONNECTTERMS_DOC, getPFINameFromFriendlyWords, ConnectTerms

ReadWrite = DataAccess.ReadWrite
ReadOnly = DataAccess.ReadOnly

CHANNELDEVNAMES_DOC = ('Comma separated Ni660XCounter Tango device names ',
                       ' configured with COPulseChanTime as applicationType.',
                       ' The 1st name in the list will be used by the 1st',
                       ' axis, etc.')
START_TRIGGER_SOURCE_DOC = ('Start trigger source, normally is the source '
                          'channel, the default value is /Dev1/PFI39 channel '
                            '0 source')
START_TRIGGER_TYPE_DOC = ('Trigger type, by default is DigEdge')

def eval_state(state):
    """This function converts Ni660X device states into counters state."""
    if state == PyTango.DevState.RUNNING:
        return State.Moving
    elif state == PyTango.DevState.STANDBY:
        return State.On
    else:
        return from_tango_state_to_state(state)

class Ni660XTriggerGateController(TriggerGateController):

    MaxDevice = 32
    min_time = 25e-6

    ctrl_properties = {
        'channelDevNames': {
            Type: str,
            Description: CHANNELDEVNAMES_DOC
        },
        'startTriggerSource':{
            Type: str,
            Description: START_TRIGGER_SOURCE_DOC,
            DefaultValue:"/Dev1/PFI39"
        },
        "startTriggerType" :{
            Type: str,
            Description: START_TRIGGER_TYPE_DOC,
            DefaultValue: "DigEdge"},
        'connectTerms': {
            Type: str,
            Description: CONNECTTERMS_DOC,
            DefaultValue: '{}'
        }
    }
    axis_attributes = {
        "slave": {
            Type: bool,
            Access: ReadWrite,
            Memorize: Memorized,
            Default: False
        },
        "retriggerable": {
            Type: bool,
            Access: ReadWrite,            
            Memorize: Memorized
        },
        "extraInitialDelayTime": {
            Type: float,
            Access: ReadWrite,
            Memorize: Memorized,
            DefaultValue: 0
        },
        'idleState': {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized,
            DefaultValue: IdleState.NOT_SET.value
        },
        'dutyCycle': {
            Type: float,
            Access: ReadWrite,
            Memorize: Memorized,
            DefaultValue: 100
        },
        'startTriggerSource': {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized,
        },
        'triggerSourceType': {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized,
            DefaultValue: "DigEdge"
        },
    }

    # relation between state and status  
    state_to_status = {
        State.On: 'Device finished generation of pulses',
        State.Standby: 'Device is standby',
        State.Moving: 'Device is generating pulses'
    }

    def __init__(self, inst, props, *args, **kwargs):
        """
        Construct the TriggerGateController and prepare the controller
        properties.
        """
        TriggerGateController.__init__(self, inst, props, *args, **kwargs)
        self.channel_names = self.channelDevNames.split(",")
        self.channels = {}
        self.slave = {}
        self.retriggerable = False
        self.extraInitialDelayTime = 0
        self.idle_states = {}
        self.duty_cycles = {}
        self.start_trigger_source = {}
        self.trigger_source_type = {}
        self.connect_terms_util = ConnectTerms(self.connectTerms)

    def AddDevice(self, axis):
        """
        Add axis to the controller, basically creates a taurus device of
        the corresponding channel.
        """
        channel_name = self.channel_names[axis - 1]
        try:
            self.channels[axis] = PyTango.DeviceProxy(channel_name)
        except Exception as e:
            msg = 'Could not create taurus device: %s, details: %s' %\
                  (channel_name, e)
            self._log.debug(msg)

    def DeleteDevice(self, axis):
        """
        Remove axis from the controller, basically forgets about the taurus
        device of the corresponding channel.
        """
        self.channels.pop(axis)
        self.idle_states.pop(axis, None)
        self.duty_cycles.pop(axis, None)
        self.start_trigger_source.pop(axis, None)
        self.trigger_source_type.pop(axis, None)

    def _getState(self, axis):
        channel = self.channels[axis]    
        state = channel.read_attribute('State').value
        if state == PyTango.DevState.RUNNING:
           return State.Moving
        elif state == PyTango.DevState.STANDBY:
           return State.On
        else:
           return from_tango_state_to_state(state)
 
    def SynchOne(self, axis, configuration):
        """
        Set axis configuration.
        """

        group = configuration[0]
        delay = group[SynchParam.Delay][SynchDomain.Time]
        active = group[SynchParam.Active][SynchDomain.Time] * (self.duty_cycles[axis]/100)
        total = group[SynchParam.Total][SynchDomain.Time]
        passive = total - active
        repeats = group[SynchParam.Repeats]

        # TODO: write of some attrs require that the device is STANDBY
        # For the moment Sardana leaves the TriggerGate elements in the 
        # state that they finished the last generation. In case of 
        # Ni660XCounter, write of some attributes require the channel 
        # to be in STANDBY state. Due to that we stop the channel.
        
        channel = self.channels[axis]          
        if self._getState(axis) is State.On:
            channel.stop()

        channel.write_attribute("HighTime", active)

        if passive < self.min_time:
            channel.write_attribute("LowTime", self.min_time)
            self._log.warning("Changing passive time to the ni660x minimum")
        else:
            channel.write_attribute("LowTime", passive)

        channel.write_attribute("SampPerChan", int(repeats))

        if self.idle_states[axis] != IdleState.NOT_SET:
            channel.write_attribute("IdleState", self.idle_states[axis].value)
                     
        timing_type = 'Implicit'
        
        # Check if the axis trigger generator needs a master trigger to start        
        if self.slave[axis]:
            startTriggerSource = self.startTriggerSource
            startTriggerType = self.startTriggerType
            if self.start_trigger_source.get(axis) is not None and \
                self.start_trigger_source.get(axis) != "":
                startTriggerSource = self.start_trigger_source[axis]
                startTriggerType = self.trigger_source_type[axis]
                msg = "startTriggerSource is set for axis {}. Using axis attribute {}" \
                      "instead of controller property {}.".format(axis, startTriggerSource, self.startTriggerSource)
                self._log.warning(msg)
            # If the trigger is manage by external trigger the delay time should be 0
            delay = 0        
            # The trigger should be retriggerable by external trigger?
            if self.retriggerable:
                channel.write_attribute('retriggerable',1)
                timing_type = 'OnDemand'
                # Set the LowTime to the minimum value. It is needed because
                # the latency time of the measurement group does not take
                # care the latency time of the trigger, and when we use the
                # NI as slave of the icepapa or pmac it needs time to
                # prepare the next trigger.
                channel.write_attribute("LowTime", 0.000003)
        else:
            startTriggerSource = 'None'
            startTriggerType = 'None'            
                                
        channel.write_attribute("StartTriggerSource", startTriggerSource)
        channel.write_attribute("StartTriggerType", startTriggerType)
        delay = delay + self.extraInitialDelayTime
        self.extraInitialDelayTime = 0
        channel.write_attribute("InitialDelayTime", delay)
        channel.write_attribute('SampleTimingType', timing_type)
        
    def PreStartOne(self, axis, value=None):
        """
        Prepare axis for generation.
        """
        self._log.debug('PreStartOne(%d): entering...' % axis)
 
        self._log.debug('PreStartOne(%d): leaving...' % axis)
        return True

    def PreStartAll(self):
        self._log.debug("PreStartAll(): Entering...")
        # Apply connect terms
        self.connect_terms_util.apply_connect_terms()
        self._log.debug("PreStartAll(): Leaving...")
        return True

    def StartOne(self, axis):
        """
        Start generation - start the specified channel.
        """
        self._log.debug('StartOne(%d): entering...' % axis)
        channel = self.channels[axis]
        channel.Start()
        self._log.debug('StartOne(%d): leaving...' % axis)

    def StateOne(self, axis):
        """
        Get state from the channel and translate it to the Sardana state
        """
        self._log.debug('StateOne(%d): entering...' % axis)
        
        sta = self._getState(axis)
        status = self.state_to_status[sta]
        self._log.debug('StateOne(%d): returning (%s, %s)'\
                             % (axis, sta, status))
        return sta, status

    def AbortOne(self, axis):
        """
        Abort generation - stop the specified channel
        """
        self._log.debug('AbortOne(%d): entering...' % axis)
        channel = self.channels[axis]
        channel.Stop()
        self._log.debug('AbortOne(%d): leaving...' % axis)

    def GetAxisExtraPar(self, axis, name):
        self._log.debug("GetAxisExtraPar(%d, %s) entering..." % (axis, name))
        name = name.lower()
        if name == "slave":
            v = self.slave[axis]
        elif name == 'retriggerable':
            self.rettrigerable =  self.channels[axis].read_attribute('retriggerable').value
            v = self.retriggerable
        elif name == 'extrainitialdelaytime':
            v = self.extraInitialDelayTime
        elif name == 'idlestate':
            v = self.idle_states[axis].value
        elif name == 'dutycycle':
            v = self.duty_cycles[axis]
        elif name == 'starttriggersource':
            v = self.start_trigger_source.get(axis)
            if v is None:
                v = ""
        elif name == 'triggersourcetype':
            v = self.trigger_source_type[axis]
        return v

    def SetAxisExtraPar(self, axis, name, value):
        self._log.debug("SetAxisExtraPar(%d, %s, %s) entering..." %
                        (axis, name, value))
        name = name.lower()
        if name == "slave":
            self.slave[axis] = value
        elif name == 'retriggerable':
            if self._getState(axis) is State.On:
                self.channels[axis].stop()
            self.retriggerable = value
            self.channels[axis].write_attribute('retriggerable', value)
        elif name == 'extrainitialdelaytime':
            self.extraInitialDelayTime = value
        elif name == 'idlestate':
            idle_states = [state.value for state in IdleState]
            error_msg = "String {} must be either in {}".format(value, idle_states)
            assert value in idle_states, error_msg
            self.idle_states[axis] = IdleState(value)
        elif name == 'dutycycle':
            error_msg = "Value {} must be a percentage between 0 (not included) " + \
                        "and 100 (included): (0,100]".format(value)
            assert 0 < value <=100, error_msg
            self.duty_cycles[axis] = value
        elif name == 'starttriggersource':
            self.start_trigger_source[axis] = value
        elif name == 'triggersourcetype':
            self.trigger_source_type[axis] = value
