import PyTango
from sardana import State
from sardana.pool.pooldefs import SynchDomain, SynchParam
from sardana.pool.controller import (TriggerGateController, Type, Description,
                                     DefaultValue, Access, DataAccess, Memorize, 
                                     Memorized)

from sardana.tango.core.util import from_tango_state_to_state

from sardana_ni660x.utils import IdleState
from sardana_ni660x.utils import CONNECTTERMS_DOC, ConnectTerms

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
            DefaultValue: False
        },
        "retriggerable": {
            Type: bool,
            Access: ReadWrite,            
            Memorize: Memorized,
            DefaultValue: False
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
        'startTriggerType': {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized,
        },
        'ignoreSlaveDelay': {
            Type: bool,
            Access: ReadWrite,
            Memorize: Memorized,
            DefaultValue: True
        }
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
        self.channels = {}
        self.channel_names = self.channelDevNames.split(",")
        self.connect_terms_util = ConnectTerms(self.connectTerms)

        # Apply connect terms
        self.connect_terms_util.apply_connect_terms()

    def AddDevice(self, axis):
        """
        Add axis to the controller, basically creates a tango device of
        the corresponding channel.
        """
        channel_name = self.channel_names[axis - 1]
        channel = self.channels[axis] = {}
        try:
            channel['device'] = PyTango.DeviceProxy(channel_name)
        except Exception as e:
            msg = 'Could not create tango device: %s, details: %s' %\
                  (channel_name, e)
            self._log.debug(msg)

        channel['starttriggersource'] = self.startTriggerSource
        channel['starttriggertype'] = self.startTriggerType

    def DeleteDevice(self, axis):
        """
        Remove axis from the controller, basically forgets about the tango
        device of the corresponding channel.
        """
        self.channels.pop(axis)

    def _getState(self, axis):
        channel = self.channels[axis]['device']    
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

        channel_cfg = self.channels[axis]
        group = configuration[0]
        delay = group[SynchParam.Delay][SynchDomain.Time]
        active = group[SynchParam.Active][SynchDomain.Time] * (channel_cfg['dutycycle']/100)
        total = group[SynchParam.Total][SynchDomain.Time]
        passive = total - active
        repeats = group[SynchParam.Repeats]

        # TODO: write of some attrs require that the device is STANDBY
        # For the moment Sardana leaves the TriggerGate elements in the 
        # state that they finished the last generation. In case of 
        # Ni660XCounter, write of some attributes require the channel 
        # to be in STANDBY state. Due to that we stop the channel.

        channel = channel_cfg['device']          
        if self._getState(axis) is State.On:
            channel.stop()

        channel.write_attribute("HighTime", active)

        if passive < self.min_time:
            channel.write_attribute("LowTime", self.min_time)
            self._log.warning("Changing passive time to the ni660x minimum")
        else:
            channel.write_attribute("LowTime", passive)

        channel.write_attribute("SampPerChan", int(repeats))

        idle_state = channel_cfg['idlestate']
        if idle_state != IdleState.NOT_SET:
            channel.write_attribute("IdleState", idle_state.value)
                     
        timing_type = 'Implicit'
        
        # Check if the axis trigger generator needs a master trigger to start        
        if channel_cfg['slave']:
            start_trigger_source = channel_cfg['starttriggersource']
            start_trigger_type = channel_cfg['starttriggertype']
            
            if channel_cfg['ignoreslavedelay']:
                # If the trigger is managed by external trigger the delay time (usually acceleration time) may not be desired.
                delay = 0        

            # The trigger should be retriggerable by external trigger
            retriggerable = self.getRetriggerable(axis)
            if retriggerable:
                timing_type = 'OnDemand'
                # Set the LowTime to the minimum value. It is needed because
                # the latency time of the measurement group does not take
                # care the latency time of the trigger, and when we use the
                # NI as slave of the icepapa or pmac it needs time to
                # prepare the next trigger.
                channel.write_attribute("LowTime", 0.000003)
            
        else:
            start_trigger_source = 'None'
            start_trigger_type = 'None'            
                                
        channel.write_attribute("StartTriggerSource", start_trigger_source)
        channel.write_attribute("StartTriggerType", start_trigger_type)
        delay = delay + channel_cfg['extrainitialdelaytime']
        channel_cfg['extrainitialdelaytime'] = 0
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

        self._log.debug("PreStartAll(): Leaving...")
        return True

    def StartOne(self, axis):
        """
        Start generation - start the specified channel.
        """
        self._log.debug('StartOne(%d): entering...' % axis)
        channel = self.channels[axis]['device']
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
        channel = self.channels[axis]['device']
        channel.Stop()
        self._log.debug('AbortOne(%d): leaving...' % axis)

    def getRetriggerable(self, axis):
        return self.channels[axis]['device'].read_attribute('retriggerable').value
        
    def setRetriggerable(self, axis, value):
        device = self.channels[axis]['device'] 
        if self._getState(axis) is State.On:
            device.stop()
        device.write_attribute('retriggerable', value)
    
    def GetAxisExtraPar(self, axis, name):
        self._log.debug("GetAxisExtraPar(%d, %s) entering..." % (axis, name))
        name = name.lower()
        value = self.channels[axis][name]
        if name == 'idlestate':
            value = value.value
        
        return value
    
    def SetAxisExtraPar(self, axis, name, value):
        self._log.debug("SetAxisExtraPar(%d, %s, %s) entering..." %
                        (axis, name, value))
        name = name.lower()
        if name == 'idlestate':
            value = IdleState(value)
        elif name == 'dutycycle':
            error_msg = ("Value {} must be a percentage between 0 (not included) " 
                        "and 100 (included): (0,100]").format(value)
            assert 0 < value <= 100, error_msg

        self.channels[axis][name] = value
