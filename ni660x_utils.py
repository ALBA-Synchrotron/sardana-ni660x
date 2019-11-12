
from sardana.macroserver.macro import Macro, Type
import PyTango


class ni_trigger(Macro):
    """
    This macro starts a sequence of triggers  as configured by the
    config_ni_trigger macro. By default, launches a single trigger sequence.
    It assumes that the name of the channel from the ni660x is stored in a
    environment variable. This is used to create the proxy and start the
    sequence.
    """
    param_def = [['ntriggers', Type.Integer, 1, 'Total number of triggers']]

    def run(self, ntriggers):
        ni_channel_name = self.getEnv('NITriggerChannel')
        channel = PyTango.DeviceProxy(ni_channel_name)
        channel.command_inout('Stop')
        channel.write_attribute("SampPerChan", long(ntriggers))
        channel.command_inout('Start')


class config_ni_trigger(Macro):
    """
    This macro configures a given channel of the ni660x card to operate
    as a trigger generator. It assumes that the name of the channel
    from the ni660x is stored in a environment variable. This is used
    to create the proxy and setup the configuration.
    """
    param_def = [['high_time', Type.String, None, 'Time on high state.'],
                 ['low_time', Type.Float, None, 'Time on high state.'],
                 ['ntriggers', Type.Integer, 1, 'Total number of triggers'],
                 ['idle_state', Type.String, 'Low', 'Idle state value'],
                 ['delay_time', Type.Float, 0, 'Delay before first trigger']]

    def run(self, high_time, low_time, ntriggers, idle_state, delay_time):
        ni_channel_name = self.getEnv('NITriggerChannel')
        channel = PyTango.DeviceProxy(ni_channel_name)
        channel.command_inout('Stop')
        channel.command_inout('Init')
        channel.write_attribute("InitialDelayTime", delay_time)
        channel.write_attribute("HighTime", high_time)
        channel.write_attribute("LowTime", low_time)
        channel.write_attribute("SampPerChan", long(ntriggers))
        channel.write_attribute("IdleState", idle_state)
        channel.write_attribute("SampleTimingType", "Implicit")

