from sardana.macroserver.macro import Macro, Type, Hookable
import taurus
import PyTango


NI660X_PFI = {'C0O': 'PFI36', 'C0A': 'PFI37', 'C0G': 'PFI38', 'C0S': 'PFI39',
              'C1O': 'PFI32', 'C1A': 'PFI33', 'C1G': 'PFI34', 'C1S': 'PFI35',
              'C2O': 'PFI28', 'C2A': 'PFI29', 'C2G': 'PFI30', 'C2S': 'PFI31',
              'C3O': 'PFI24', 'C3A': 'PFI25', 'C3G': 'PFI26', 'C3S': 'PFI27',
              'C4O': 'PFI20', 'C4A': 'PFI21', 'C4G': 'PFI22', 'C4S': 'PFI23',
              'C5O': 'PFI16', 'C5A': 'PFI17', 'C5G': 'PFI18', 'C5S': 'PFI19',
              'C6O': 'PFI12', 'C6A': 'PFI13', 'C6G': 'PFI14', 'C6S': 'PFI15',
              'C7O': 'PFI08', 'C7A': 'PFI09', 'C7G': 'PFI10', 'C7S': 'PFI11'}


class ni_trigger(Macro, Hookable):
    """
    This macro starts a sequence of triggers  as configured by the
    config_ni_trigger macro. By default, launches a single trigger sequence.
    It assumes that the name of the channel from the ni660x is stored in a
    environment variable. This is used to create the proxy and start the
    sequence.
    """
    param_def = [['ntriggers', Type.Integer, 0, 'Total number of triggers']]

    def run(self, ntriggers):
        ni_channel_name = self.getEnv('NITriggerChannel')
        channel = taurus.Device(ni_channel_name)
        channel.command_inout('Stop')
        if ntriggers > 0:
            channel.write_attribute("SampPerChan", int(ntriggers))
        channel.command_inout('Start')


class ni_config_trigger(Macro):
    """
    This macro configures a given channel of the ni660x card to operate
    as a trigger generator. It assumes that the name of the channel
    from the ni660x is stored in a environment variable. This is used
    to create the proxy and setup the configuration.
    """
    param_def = [['high_time', Type.Float, None, 'Time on high state.'],
                 ['low_time', Type.Float, None, 'Time on high state.'],
                 ['ntriggers', Type.Integer, 1, 'Total number of triggers'],
                 ['idle_state', Type.String, 'Low', 'Idle state value'],
                 ['delay_time', Type.Float, 0, 'Delay before first trigger']]

    def run(self, high_time, low_time, ntriggers, idle_state, delay_time):
        ni_channel_name = self.getEnv('NITriggerChannel')
        channel = taurus.Device(ni_channel_name)
        channel.command_inout('Stop')
        channel.write_attribute("InitialDelayTime", delay_time)
        channel.write_attribute("HighTime", high_time)
        channel.write_attribute("LowTime", low_time)
        channel.write_attribute("SampPerChan", int(ntriggers))
        channel.write_attribute("IdleState", idle_state)
        channel.write_attribute("SampleTimingType", "Implicit")


class ni_connect_channels(Macro):
    """
    This macro connect the given channel signals on the NI6602. The channels
    are identified by: RTSI[0-7] and/or C[0-7][O,S,G,A] , where the letters
    are:
        - O: Output
        - S: Source
        - G: Gate
        - A: Auxiliary
    To introduce the channel you should include the card: Dev[1-n].

    Requirements:
        - This macro use the environment variable NI660XDsName.
        - Sardana 2.0 API.
    """

    param_def = [['channels', [['channel', Type.String, None, '/Dev1/C10'],
                               {'min': 2}], None, 
                  'List of channels and internal signals'],
                 ['polarity', Type.String, 'DoNotInvertPolarity', 
                  'Polarity connection']]

    def run(self, channels, polarity):
        connect_list = []
        try:
            ni_device_name = self.getEnv('NI660XDsName')
        except Exception as e:
            self.error('You should declare the Ni660XDsName. %s' % e)

        ni_device = taurus.Device(ni_device_name)

        for chn in channels:
            chn = chn.upper()
            if 'RTSI' not in chn:
                # Change the channel name by its PFI
                dev_chn = chn.rsplit('/', 1)
                dev_chn[1] = NI660X_PFI[dev_chn[1]]
                chn = '/'.join(dev_chn)
            connect_list.append(chn)

        for pair in connect_list[1:]:
            cmd = [connect_list[0], pair]
            self.debug(cmd)
            ni_device.DisconnectTerms(cmd)

        # Include the last parameter DoNotInvertPolarity or InvertPolarity
        for pair in connect_list[1:]:
            cmd = [connect_list[0], pair, polarity]
            self.debug(cmd)
            ni_device.ConnectTerms(cmd)


class ni_config_counter(Macro):
    """
    This macro configure the counter and the master trigger channels  to use 
    them on step or continuous scan.

    Requirements:
        - The macro use the environment variables NIMasterTrigger, NICountersDS 
          (list of device names) and NIMasterSignal (signal use for the counters 
          as timer e.g: /Dev1/RTSI0, /Dev2/PFI36).
        - The counters should configure with the application: CICountEdgesChan.
    """

    param_def = [['mode', Type.String, None, 'continuous or step']]

    def run(self, mode):
        mode = mode.lower()
        if mode not in ['continuous', 'step']:
            raise ValueError('The value should be: continuous or step')
        try:
            ni_chn_names = self.getEnv('NICountersDS')
            ni_signal_master = self.getEnv('NIMasterSignal')
            ni_channel_master = self.getEnv('NIMasterTrigger')
        except Exception as e:
            msg_err = 'You should declare NICountersDS, ' \
                      'NIMasterSignal and NIMasterTrigger. %s' % e
            self.error(msg_err)

        if mode == 'continuous':
            for ni_chn_name in ni_chn_names:
                chn_proxy = taurus.Device(ni_chn_name)
                chn_proxy.init()
                chn_proxy.write_attribute('SampleClockSource',
                                          ni_signal_master)
                chn_proxy.write_attribute('SampleTimingType',  'SampClk')
                if ni_chn_names.index(ni_chn_name) > 4:
                    chn_proxy.write_attribute('DataTransferMechanism',
                                              'Interrupts')
        else:
            for ni_chn_name in ni_chn_names:
                chn_proxy = taurus.Device(ni_chn_name)
                chn_proxy.init()
                chn_proxy.write_attribute('PauseTriggerType', 'DigLvl')
                chn_proxy.write_attribute('PauseTriggerSource',
                                          ni_signal_master)
                chn_proxy.write_attribute('PauseTriggerWhen', 'Low')
            master_proxy = PyTango.DeviceProxy(ni_channel_master)
            master_proxy.init()
            master_proxy.write_attribute('InitialDelayTime', 0)
            master_proxy.write_attribute('LowTime', 0.001)
            master_proxy.write_attribute('SampPerChan', int(1))
