# -*- coding: utf-8 -*-

"""
:author: Rinze de Laat <laat@delmic.com>
:copyright: © 2013 Rinze de Laat, Delmic

This file is part of Odemis.

.. license::
    Odemis is free software: you can redistribute it and/or modify it under the terms  of the GNU
    General Public License version 2 as published by the Free Software  Foundation.

    Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;  without
    even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR  PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License along with Odemis. If not,
    see http://www.gnu.org/licenses/.

Module purpose
--------------

This module contains functions that help in the generation of dynamic configuration values.

"""

from __future__ import division

from collections import OrderedDict
import collections
import logging
import math
import numbers
import odemis.gui
from odemis.gui.comp.file import EVT_FILE_SELECT
from odemis.gui.util.widgets import VigilantAttributeConnector, AxisConnector
from odemis.model import NotApplicableError
from odemis.util.conversion import reproduce_typed_value
from odemis.util.units import readable_str, to_string_si_prefix, decompose_si_prefix, \
    si_scale_val
import re
import wx
from wx.lib.pubsub import pub

import odemis.gui.conf as guiconf
import odemis.util.units as utun


def resolution_from_range(comp, va, conf, init=None):
    """ Construct a list of resolutions depending on range values

    init (set or None): values that will be always in the choices. If None, it will just ensure that
        the current value is present.

    """

    cur_val = va.value

    if len(cur_val) != 2:
        logging.warning("Got a resolution not of length 2: %s", cur_val)
        return {cur_val: str(cur_val)}

    try:
        if init is None:
            choices = {cur_val}
        else:
            choices = init
        num_pixels = cur_val[0] * cur_val[1]
        res = va.range[1]  # start with max resolution

        for _ in range(10):
            choices.add(res)
            res = (res[0] // 2, res[1] // 2)

            if len(choices) >= 4 and (res[0] * res[1] < num_pixels):
                break

        choices = sorted(list(choices))
        return OrderedDict(tuple((v, "%d x %d" % v) for v in choices))
    except NotApplicableError:
        return {cur_val: str(cur_val)}


def resolution_from_range_plus_point(comp, va, conf):
    """ Same as resolution_from_range() but also add a 1x1 value """
    return resolution_from_range(comp, va, conf, init={va.value, (1, 1)})


MIN_RES = 128 * 128  # px, minimum amount of pixels to consider it acceptable


def binning_1d_from_2d(comp, va, conf):
    """ Find simple binnings available in one dimension

    We assume pixels are always square. The binning provided by a camera is normally a 2-tuple of
    integers.

    Note: conf can have a special parameter "range_1d" to limit the choices generated
    """
    cur_val = va.value
    if len(cur_val) != 2:
        logging.warning("Got a binning not of length 2: %s, will try anyway", cur_val)

    try:
        nbpx_full = comp.shape[0] * comp.shape[1]  # res at binning 1
        choices = {cur_val[0]}
        minbin = max(va.range[0])
        maxbin = min(va.range[1])
        if "range_1d" in conf:
            conf_rng = conf["range_1d"]
            minbin = max(conf_rng[0], minbin)
            maxbin = min(conf_rng[1], maxbin)

        # add up to 5 binnings
        b = int(math.ceil(minbin))  # in most cases, that's 1
        for _ in range(6):
            # does it still make sense to add such a small binning?
            if b > cur_val[0]:
                nbpx = nbpx_full / (b ** 2)
                if nbpx < MIN_RES: # too small resolution
                    break
                if len(choices) >= 5: # too many choices
                    break

            if b > maxbin:
                break

            choices.add(b)
            b *= 2

        choices = sorted(list(choices))
        return OrderedDict(tuple(((v, v), str(int(v))) for v in choices))
    except NotApplicableError:
        return {cur_val: str(cur_val[0])}


def binning_firstd_only(comp, va, conf):
    """ Find simple binnings available in the first dimension

    The second dimension stays at a fixed size.

    """
    cur_val = va.value

    try:
        choices = {cur_val[0]}
        minbin = va.range[0][0]
        maxbin = va.range[1][0]

        # add up to 5 binnings
        b = int(math.ceil(minbin))  # in most cases, that's 1
        for _ in range(6):
            if minbin <= b <= maxbin:
                choices.add(b)

            if len(choices) >= 5 and b >= cur_val[0]:
                break

            b *= 2

        choices = sorted(list(choices))
        return OrderedDict(tuple(((v, cur_val[1]), str(int(v))) for v in choices))
    except NotApplicableError:
        return {cur_val: str(cur_val[0])}


def hfw_choices(comp, va, conf):
    """ Return a list of HFW choices

    If the VA has predefined choices, return those. Otherwise calculate the choices using the range
    of the VA.

    """

    try:
        choices = va.choices
    except (NotApplicableError, AttributeError):
        mi, ma, = va.range
        choices = [mi]
        step = 1
        while choices[-1] < ma:
            choices.append(mi * 10 ** step)
            step += 1
        choices[-1] = ma
    return choices


def mag_if_no_hfw_ctype(comp, va, conf):
    """ Return the control type for e-beam magnification

    This control is only useful if it's writeable (meaning that the ebeam
      component cannot control the magnification so the user has to type it in)

    :return: (int) The control type

    """

    # if hasVA(comp, "horizontalFoV"):
    if va.readonly:
        return odemis.gui.CONTROL_NONE
    else:
        # Just use a text field => it's for copy-paste
        return odemis.gui.CONTROL_FLT

# END Setting choice generators


def determine_default_control(va):
    """ Determine the default control to use to represent a vigilant attribute

    :param va: (VigilantAttribute)

    :return: (odemis.gui.CONTROL_*)

    """

    if not va:
        logging.warn("No VA provided!")
        return odemis.gui.CONTROL_NONE

    if va.readonly:
        # Uncomment this line to hide Read only VAs by default
        # return odemis.gui.CONTROL_NONE
        return odemis.gui.CONTROL_READONLY
    else:
        try:
            # This statement will raise an exception when no choices are present
            logging.debug("Found choices %s", va.choices)

            max_num_choices = 5
            max_value_len = 5

            # If there are too many choices, or their values are too long in string
            # representation, use a drop-down box

            choices_str = "".join([str(c) for c in va.choices])

            if len(va.choices) <= 1:
                # One or no choices, so the control can be read only
                return odemis.gui.CONTROL_READONLY
            elif (len(va.choices) < max_num_choices and
                  len(choices_str) < max_num_choices * max_value_len):
                # Short strings values can be accommodated by radio buttons
                return odemis.gui.CONTROL_RADIO
            else:
                # Combo boxes (drop down) are used otherwise
                return odemis.gui.CONTROL_COMBO
        except (AttributeError, NotApplicableError):
            pass

        try:
            # An exception will be raised if no range attribute is found
            logging.debug("Found range %s", va.range)

            # TODO: if unit is "s" => scale=exp
            if isinstance(va.value, (int, long, float)):
                # If the value is a number with a range, return the slider control
                return odemis.gui.CONTROL_SLIDER
        except (AttributeError, NotApplicableError):
            pass

        # Simple input => look at the type
        val = va.value
        if isinstance(val, bool):
            return odemis.gui.CONTROL_CHECK
        elif isinstance(val, (int, long)):
            return odemis.gui.CONTROL_INT
        elif isinstance(val, float):
            return odemis.gui.CONTROL_FLT

        # Return default control
        return odemis.gui.CONTROL_TEXT


def determine_control_type(hw_comp, va, choices_formatted, conf):
    """ Determine the control type for the given VA """

    # Get the defined type of control or assign a default one
    try:
        control_type = conf['control_type']
    except KeyError:
        control_type = determine_default_control(va)

    if callable(control_type):
        control_type = control_type(hw_comp, va, conf)

    # Change radio type to fitting type depending on its content
    if control_type == odemis.gui.CONTROL_RADIO:
        if len(choices_formatted) <= 1:  # only one choice => force label
            control_type = odemis.gui.CONTROL_READONLY
            logging.warn("Radio control changed to read only because of lack of choices!")
        elif len(choices_formatted) > 10:  # too many choices => combo
            control_type = odemis.gui.CONTROL_COMBO
            logging.warn("Radio control changed to combo box because of number of choices!")
        else:
            # choices names too long => combo
            max_len = max([len(f) for _, f in choices_formatted])
            if max_len > 6:
                control_type = odemis.gui.CONTROL_COMBO
                logging.warn("Radio control changed to combo box because of max value length!")

    # read-only takes precedence (unless it was requested to hide it)
    if va.readonly and control_type != odemis.gui.CONTROL_NONE:
        control_type = odemis.gui.CONTROL_READONLY

    return control_type


def bind_setting_context_menu(settings_entry):
    """ Add a context menu to the settings entry to reset it to its original value

    The added menu is used in the acquisition window, to give the user the ability to reset values
    that have been adjusted by Odemis.

    :param settings_entry: (SettingEntry) Must at least have a valid label, ctrl and va

    """
    if settings_entry.value_ctrl is None:
        logging.debug("Skipping highlight of %s, as it has no control",
                      settings_entry.name)
        return

    orig_val = settings_entry.vigilattr.value

    def reset_value(_):
        """ Reset the value of the setting VA back to its original value """
        settings_entry.vigilattr.value = orig_val
        wx.CallAfter(pub.sendMessage, 'setting.changed')

    def show_reset_menu(evt):
        """ Create and show a context menu which has a menu item to reset the settings's value """
        menu = wx.Menu()
        mi = wx.MenuItem(menu, wx.NewId(), 'Reset value')
        eo = evt.GetEventObject()
        eo.Bind(wx.EVT_MENU, reset_value, mi)
        menu.AppendItem(mi)
        # Disable the menu item if the value has not changed
        disable = settings_entry.vigilattr.value != orig_val
        mi.Enable(disable)
        # Show the menu
        eo.PopupMenu(menu)

    # Bind the menu to both the label and the value controls
    settings_entry.value_ctrl.Bind(wx.EVT_CONTEXT_MENU, show_reset_menu)
    settings_entry.lbl_ctrl.Bind(wx.EVT_CONTEXT_MENU, show_reset_menu)


def process_setting_metadata(hw_comp, setting_va, conf):
    """ Process and return metadata belonging to the given VA

    Values will be built from the value of the VA, its properties and the provided configuration.

    Args:
        hw_comp (Component): Hardware component to which the VA belongs
        setting_va (VigilantAttribute): The VA containing the value of the setting
        conf (dict): A dictionary containing various configuration values for the setting

    Returns:
        (minimum value, maximum value, choices, unit)

        Where min and max values are numerical, choices is an iterable (list, dict or set) or None
        and unit is a string.


    """

    # Range might be a value tuple or a callable that calculates the range
    r = conf.get("range", (None, None))
    minv, maxv = (None, None)

    try:
        # Calculate the range of the VA
        if callable(r):
            minv, maxv = r(hw_comp, setting_va, conf)
        # Get the range directly from the va itself, if it's not configured
        elif r == (None, None):
            minv, maxv = setting_va.range
        # Combine the configured range with the range from the VA itself
        else:
            # TODO: handle iterables
            minv, maxv = r
            minv, maxv = max(minv, setting_va.range[0]), min(maxv, setting_va.range[1])
    except (AttributeError, NotApplicableError):
        pass

    # Ensure the range encompasses the current value
    if None not in (minv, maxv):
        val = setting_va.value
        if isinstance(val, numbers.Real):
            minv, maxv = min(minv, val), max(maxv, val)

    choices = conf.get("choices", None)

    try:
        if callable(choices):
            choices = choices(hw_comp, setting_va, conf)
        elif choices is None:
            choices = setting_va.choices
        elif hasattr(setting_va, "choices") and isinstance(setting_va.choices, set):
            # Intersect the two choice sets
            choices &= setting_va.choices
        elif hasattr(setting_va, "choices") and isinstance(setting_va.choices, collections.Mapping):  # dicts
            # Only keep the items of va.choices which are also choices
            choices = {k: v for k, v in setting_va.choices.items() if k in choices}
        elif hasattr(setting_va, "range") and isinstance(setting_va.range, collections.Iterable):
            # Ensure that each choice is within the range
            # TODO: handle iterables
            rng = setting_va.range
            choices = set(c for c in choices if rng[0] <= c <= rng[1])
    except (AttributeError, NotApplicableError), e:
        pass

    # Ensure the choices are within the range (if both are given)
    # TODO: handle iterables
    if choices is not None and None not in (minv, maxv) and not isinstance(minv, collections.Iterable):
        logging.debug("Restricting choices %s to range %s->%s", choices, minv, maxv)
        if isinstance(choices, collections.Mapping):  # dicts
            choices = {k: v for k, v in choices.items() if minv <= k <= maxv}
        else:
            choices = set(c for c in choices if minv <= c <= maxv)

    # Ensure the choices contain the current value
    if choices is not None and setting_va.value not in choices:
        logging.info("Current value %s not in choices %s", setting_va.value, choices)
        if isinstance(choices, set):
            choices.add(setting_va.value)
        elif isinstance(choices, dict):
            choices[setting_va.value] = unicode(setting_va.value)
        elif isinstance(choices, list):
            # FIXME: The HFW choices are the only choices provided as a Python list, and it's
            # not necessary to add the current value to the choices. That's why, for now,
            # the `list` type is ignored here. However, it would be better to either allow for
            # the current value to be added to the HFW choices, or to disable the adding of it in
            # some explicit way.
            pass
        else:
            logging.warning("Don't know how to extend choices of type %s", type(choices))

    # Get unit from config, vigilant attribute or use an empty one
    unit = conf.get('unit', setting_va.unit or "")

    return minv, maxv, choices, unit


def format_choices(choices, uniformat=True, si=None):
    """ Transform the given choices into an ordered list of (value, formatted value) tuples

    Args:
        choices (Iterable): The choices to be formatted or None
        uniformat (bool): If True, all the values will be formatted using the same SI prefix
        si (bool): si unit to format the choice values to.
          This argument takes precedence over the `uniformat` argument.

    Returns:
        ([(value, formatted value)], si prefix) or (None, None)

    """

    if choices:
        choices_si_prefix = None

        # choice_fmt is an iterable of tuples: (choice, formatted choice)
        if isinstance(choices, dict):
            # In this case we assume that the values are already formatted
            choices_formatted = choices.items()
        elif si is not None:
            fmt, choices_si_prefix = utun.si_scale_list(choices, si)
            choices_formatted = zip(choices, [u"%g" % c for c in fmt])
        elif len(choices) > 1 and all(isinstance(c, numbers.Real) for c in choices):
            try:
                # TODO: does it matter? Can't we always do non-uniform?
                # Or just guess based on the magnitude between the lowest and biggest value?
                if uniformat:
                    fmt, choices_si_prefix = utun.si_scale_list(choices)
                    choices_formatted = zip(choices, [u"%g" % c for c in fmt])
                else:
                    fmt = []
                    for choice in choices:
                        fmt.append(to_string_si_prefix(choice, sig=3))
                    return zip(choices, fmt), choices_si_prefix
            except Exception:
                logging.exception("Formatting error!")
                choices_formatted = [(c, choice_to_str(c)) for c in choices]
        else:
            choices_formatted = [(c, choice_to_str(c)) for c in choices]

        if not isinstance(choices, OrderedDict):
            choices_formatted = sorted(choices_formatted)

        return choices_formatted, choices_si_prefix

    else:
        return None, None


def create_formatted_setter(value_ctrl, val, val_unit, sig=3):
    """ Create a setting function for the given value control that also formats its value

    Args:
        value_ctrl (wx.Window): A text control
        val: The current value of the value control
        val_unit: The unit of the value
        sig: The number of significant digits

    """

    value_formatter = None

    if (
            isinstance(val, (int, long, float)) or
            (
                isinstance(val, collections.Iterable) and
                len(val) > 0 and
                isinstance(val[0], (int, long, float))
            )
    ):
        def value_formatter(value, unit=val_unit):
            value_ctrl.SetValue(readable_str(value, unit, sig=sig))

    return value_formatter


def choice_to_str(choice, js=None):
    """ Return a list of choices, where iterable choices are joined by an `x` """
    if not isinstance(choice, collections.Iterable):
        choice = [unicode(choice)]
    return (js if js else u" x ").join([unicode(c) for c in choice])


def label_to_human(camel_label):
    """ Convert a camel-case label into a human readable string """

    # Add space after each upper case, then make the first letter uppercase and all the other ones
    # lowercase
    return re.sub(r"([A-Z])", r" \1", camel_label).capitalize()


def create_setting_entry(container, name, va, hw_comp, conf=None, change_callback=None):
    """ Determine what type on control to use for a setting and have the container create it

    Args:
        container (SettingsController or StreamController): Controller in charge of the settings
        name (str): Name of the setting
        va (VigilantAttribute): The va containing the value of the setting
        hw_comp (Component): The hardware component to which the setting belongs
        conf ({} or None): The optional configuration options for the control
        change_callback (callable): Callable to bind to the control's change event

    Returns:
        SettingEntry

    """

    value_ctrl = lbl_ctrl = setting_entry = None

    # If no conf provided, set it to an empty dictionary
    conf = conf or {}

    # Get the range and choices
    min_val, max_val, choices, unit = process_setting_metadata(hw_comp, va, conf)
    # Format the provided choices
    si = conf.get('si', None)
    si_unif = conf.get('si_unif', True)
    choices_formatted, choices_si_prefix = format_choices(choices, uniformat=si_unif, si=si)
    # Determine the control type to use, either from config or some 'smart' default
    control_type = determine_control_type(hw_comp, va, choices_formatted, conf)

    # Special case, early stop
    if control_type == odemis.gui.CONTROL_NONE:
        # No value, not even a label, just an empty entry, so that the settings are saved
        # during acquisition
        return SettingEntry(name=name, va=va, hw_comp=hw_comp)

    # Format label
    label_text = conf.get('label', label_to_human(name))
    tooltip = conf.get('tooltip', "")

    logging.debug("Adding VA %s", label_text)
    # Create the needed wxPython controls
    if control_type == odemis.gui.CONTROL_READONLY:
        val = va.value  # only format if it's a number
        accuracy = conf.get('accuracy', 3)
        lbl_ctrl, value_ctrl = container.add_readonly_field(label_text, val)
        value_formatter = create_formatted_setter(value_ctrl, val, unit, accuracy)
        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     va_2_ctrl=value_formatter)

    elif control_type == odemis.gui.CONTROL_TEXT:
        val = va.value  # only format if it's a number
        accuracy = conf.get('accuracy', 3)
        lbl_ctrl, value_ctrl = container.add_text_field(label_text, val)
        value_formatter = create_formatted_setter(value_ctrl, val, unit, accuracy)
        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     va_2_ctrl=value_formatter,
                                     events=wx.EVT_TEXT_ENTER)

    elif control_type in (odemis.gui.CONTROL_SAVE_FILE, odemis.gui.CONTROL_OPEN_FILE):
        val = va.value
        if not val:
            config = guiconf.get_acqui_conf()
            val = config.last_path

        if control_type == odemis.gui.CONTROL_SAVE_FILE:
            dialog_style = wx.FD_SAVE
        else:  # odemis.gui.CONTROL_OPEN_FILE
            dialog_style = wx.FD_OPEN

        clearlabel = conf.get('clearlabel')  # Text to show when no filename (+ allow to clear the filename)
        lbl_ctrl, value_ctrl = container.add_file_button(label_text,
                                                         val,
                                                         clearlabel,
                                                         dialog_style=dialog_style)

        # TODO: allow to change the wildcard via a conf key?
        # value_ctrl.SetWildcard(wildcards)

        # Add the corresponding setting entry
        setting_entry = SettingEntry(name=label_text, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=EVT_FILE_SELECT)

    elif control_type == odemis.gui.CONTROL_SLIDER:
        # The slider is accompanied by an extra number text field

        if "type" in conf:
            if conf["type"] == "integer":
                # add_integer_slider
                factory = container.add_integer_slider
            elif conf["type"] == "slider":
                factory = container.add_slider
            else:
                factory = container.add_float_slider
        else:
            # guess from value(s)
            known_values = [va.value, min_val, max_val]
            if choices is not None:
                known_values.extend(list(choices))
            if any(isinstance(v, float) for v in known_values):
                factory = container.add_float_slider
            else:
                factory = container.add_integer_slider

        # The event configuration determines what event will signal that the
        # setting entry has changed value.
        update_event = conf.get("event", wx.EVT_SLIDER)
        if update_event not in (wx.EVT_SCROLL_CHANGED, wx.EVT_SLIDER):
            raise ValueError("Illegal event type %d for Slider setting entry!" % (update_event,))

        ctrl_conf = {
            'min_val': min_val,
            'max_val': max_val,
            'scale': conf.get('scale', None),
            'unit': unit,
            'accuracy': conf.get('accuracy', 4),
        }

        lbl_ctrl, value_ctrl = factory(label_text, va.value, ctrl_conf)
        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=update_event)

        if change_callback:
            value_ctrl.Bind(wx.EVT_SLIDER, change_callback)

    elif control_type == odemis.gui.CONTROL_INT:
        if unit == "":  # don't display unit prefix if no unit
            unit = None

        ctrl_conf = {
            'min_val': min_val,
            'max_val': max_val,
            'unit': unit,
            'choices': choices,
        }

        lbl_ctrl, value_ctrl = container.add_int_field(label_text, conf=ctrl_conf)

        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=wx.EVT_COMMAND_ENTER)

        if change_callback:
            value_ctrl.Bind(wx.EVT_COMMAND_ENTER, change_callback)

    elif control_type == odemis.gui.CONTROL_FLT:
        if unit == "":  # don't display unit prefix if no unit
            unit = None

        ctrl_conf = {
            'min_val': min_val,
            'max_val': max_val,
            'unit': unit,
            'choices': choices,
            'accuracy': conf.get('accuracy', 5),
        }

        lbl_ctrl, value_ctrl = container.add_float_field(label_text, conf=ctrl_conf)

        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=wx.EVT_COMMAND_ENTER)

        if change_callback:
            value_ctrl.Bind(wx.EVT_COMMAND_ENTER, change_callback)

    elif control_type == odemis.gui.CONTROL_CHECK:
        # Only supports boolean VAs

        lbl_ctrl, value_ctrl = container.add_checkbox_control(label_text, value=va.value)

        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=wx.EVT_CHECKBOX)

        if change_callback:
            value_ctrl.Bind(wx.EVT_CHECKBOX, change_callback)

    elif control_type == odemis.gui.CONTROL_RADIO:
        unit_fmt = (choices_si_prefix or "") + (unit or "")

        ctrl_conf = {
            'size': (-1, 16),
            'units': unit_fmt,
            'choices': [v for v, _ in choices_formatted],
            'labels': [l for _, l in choices_formatted],
        }

        lbl_ctrl, value_ctrl = container.add_radio_control(label_text, conf=ctrl_conf)

        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     events=wx.EVT_BUTTON)

        if change_callback:
            value_ctrl.Bind(wx.EVT_BUTTON, change_callback)

    elif control_type == odemis.gui.CONTROL_COMBO:

        accuracy = conf.get('accuracy', 3)

        # TODO: Might need size=(100, 16)!!
        lbl_ctrl, value_ctrl = container.add_combobox_control(label_text)

        # Set choices
        if choices_si_prefix:
            for choice, formatted in choices_formatted:
                value_ctrl.Append(u"%s %s" % (formatted, choices_si_prefix + unit), choice)
        else:
            for choice, formatted in choices_formatted:
                value_ctrl.Append(u"%s%s" % (formatted, unit), choice)

        # A small wrapper function makes sure that the value can
        # be set by passing the actual value (As opposed to the text label)
        def cb_set(value, ctrl=value_ctrl, u=unit):
            for i in range(ctrl.Count):
                if ctrl.GetClientData(i) == value:
                    logging.debug("Setting combobox value to %s", ctrl.Items[i])
                    ctrl.SetSelection(i)
                    break
            else:
                logging.debug("No existing label found for value %s in combobox ctrl %d",
                              value, id(ctrl))
                # entering value as free text
                txt = readable_str(value, u, sig=accuracy)
                return ctrl.SetValue(txt)

        # equivalent wrapper function to retrieve the actual value
        def cb_get(ctrl=value_ctrl, va=va, u=unit):
            ctrl_value = ctrl.GetValue()
            # Try to use the predefined value if it's available
            i = ctrl.GetSelection()

            # Warning: if the text contains an unknown value, GetSelection will
            # not return wx.NOT_FOUND (as expected), but the last selection value
            if i != wx.NOT_FOUND and ctrl.Items[i] == ctrl_value:
                logging.debug("Getting item value %s from combobox control",
                              ctrl.GetClientData(i))
                return ctrl.GetClientData(i)
            else:
                logging.debug("Parsing combobox free text value %s", ctrl_value)
                va_val = va.value
                # Try to find a good corresponding value inside the string

                # Try and find an SI prefix
                str_val, str_si, _ = decompose_si_prefix(ctrl_value, unit=u)

                new_val = reproduce_typed_value(va_val, str_val)

                if isinstance(new_val, collections.Iterable):
                    # be less picky, by shortening the number of values if it's too many
                    new_val = new_val[:len(va_val)]

                # If an SI prefix was found, scale the new value
                new_val = si_scale_val(new_val, str_si)

                # if it ends up being the same value as before the combobox will not update, so
                # force it now
                if va_val == new_val:
                    cb_set(va_val)
                return new_val

        setting_entry = SettingEntry(name=name, va=va, hw_comp=hw_comp,
                                     lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                     va_2_ctrl=cb_set, ctrl_2_va=cb_get,
                                     events=(wx.EVT_COMBOBOX, wx.EVT_TEXT_ENTER))
        if change_callback:
            value_ctrl.Bind(wx.EVT_COMBOBOX, change_callback)
            value_ctrl.Bind(wx.EVT_TEXT_ENTER, change_callback)

    else:
        logging.error("Unknown control type %s", control_type)

    value_ctrl.SetToolTipString(tooltip)
    lbl_ctrl.SetToolTipString(tooltip)

    return setting_entry


def create_axis_entry(container, name, comp, conf=None):
    # If no conf provided, set it to an empty dictionary
    conf = conf or {}

    # Format label
    label_text = conf.get('label', label_to_human(name))
    tooltip = conf.get('tooltip', "")

    logging.debug("Adding Axis control %s", label_text)

    ad = comp.axes[name]
    pos = comp.position.value[name]
    unit = ad.unit

    # If axis has .range (continuous) => slider
    # If axis has .choices (enumerated) => combo box
    if hasattr(ad, "range"):
        if "range" in conf:
            minv, maxv = conf["range"]
        else:
            minv, maxv = ad.range

        ctrl_conf = {
            'min_val': minv,
            'max_val': maxv,
            'unit': unit,
            'accuracy': conf.get('accuracy', 3),
        }

        lbl_ctrl, value_ctrl = container.add_float_slider(label_text, pos, ctrl_conf)

        # don't bind to wx.EVT_SLIDER, which happens as soon as the slider moves,
        # but to EVT_SCROLL_CHANGED, which happens when the user has made his
        # mind. This avoid too many unnecessary actuator moves and disabling the
        # widget too early.
        axis_entry = AxisSettingEntry(name, comp, lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                      events=wx.EVT_SCROLL_CHANGED)
    else:
        # FIXME: should be readonly, but it fails with GetInsertionPoint (wx.CB_READONLY)
        lbl_ctrl, value_ctrl = container.add_combobox_control(label_text)

        # format the choices
        choices = ad.choices

        if isinstance(choices, dict):
            # it's then already value -> string (user-friendly display)
            choices_fmt = choices.items()
            unit = None
        elif (unit and len(choices) > 1 and
              all([isinstance(c, numbers.Real) for c in choices])):
            # TODO: need same update as add_value
            fmt, prefix = utun.si_scale_list(choices)
            choices_fmt = zip(choices, [u"%g" % c for c in fmt])
            unit = prefix + unit
        else:
            choices_fmt = [(c, choice_to_str(c)) for c in choices]

        choices_fmt = sorted(choices_fmt) # sort 2-tuples = according to first value in tuple

        # FIXME: Is this still needed?
        def _eat_event(evt):
            """ Quick and dirty empty function used to 'eat' mouse wheel events """
            pass
        value_ctrl.Bind(wx.EVT_MOUSEWHEEL, _eat_event)

        # Set choices
        if unit is None:
            unit = ""
        for choice, formatted in choices_fmt:
            value_ctrl.Append(u"%s %s" % (formatted, unit), choice)

        # A small wrapper function makes sure that the value can
        # be set by passing the actual value (As opposed to the text label)
        def cb_set(value, ctrl=value_ctrl, unit=unit):
            for i in range(ctrl.Count):
                if ctrl.GetClientData(i) == value:
                    logging.debug("Setting ComboBox value to %s", ctrl.Items[i])
                    return ctrl.SetValue(ctrl.Items[i])
            else:
                logging.warning("No existing label found for value %s", value)
                return ctrl.GetValue()

        # equivalent wrapper function to retrieve the actual value
        def cb_get(ctrl=value_ctrl, name=name):
            value = ctrl.GetValue()
            # Try to use the predefined value if it's available
            for i in range(ctrl.Count):
                if ctrl.Items[i] == value:
                    logging.debug("Getting CB value %s", ctrl.GetClientData(i))
                    return ctrl.GetClientData(i)
            else:
                logging.error("Failed to find value %s for axis %s", value, name)

        axis_entry = AxisSettingEntry(name, comp, lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                      pos_2_ctrl=cb_set, ctrl_2_pos=cb_get,
                                      events=(wx.EVT_COMBOBOX, wx.EVT_TEXT_ENTER))

    value_ctrl.SetToolTipString(tooltip)
    lbl_ctrl.SetToolTipString(tooltip)

    return axis_entry


class Entry(object):
    """ Describes a setting entry in the settings panel """

    def __init__(self, name, hw_comp, stream, lbl_ctrl, value_ctrl):
        """
        :param name: (str): The name of the setting
        :param hw_comp: (Component): The component to which the setting belongs
        :param stream: (Stream) The stream with which the Entry is associated
        :param lbl_ctrl: (wx.StaticText): The setting label
        :param value_ctrl: (wx.Window): The widget containing the current value

        """

        self.name = name
        self.hw_comp = hw_comp
        self.stream = stream
        self.lbl_ctrl = lbl_ctrl
        self.value_ctrl = value_ctrl

    def __repr__(self):
        r = "name: %s" % self.name

        if self.lbl_ctrl:
            r += " label: %s" % self.lbl_ctrl.GetLabel()

        if self.value_ctrl:
            r += " ctrl: %s, val: %s" % (self.value_ctrl.__class__.__name__,
                                         self.value_ctrl.GetValue())
        return r

    def highlight(self, active=True):
        """ Highlight the setting entry by adjusting its colour

        :param active: (boolean) whether it should be highlighted or not

        """

        if not self.lbl_ctrl:
            return

        if active:
            self.lbl_ctrl.SetForegroundColour(odemis.gui.FG_COLOUR_HIGHLIGHT)
        else:
            self.lbl_ctrl.SetForegroundColour(odemis.gui.FG_COLOUR_MAIN)


class SettingEntry(VigilantAttributeConnector, Entry):
    """ An Entry linked to a Vigilant Attribute """

    def __init__(self, name, va=None, hw_comp=None, stream=None, lbl_ctrl=None, value_ctrl=None,
                 va_2_ctrl=None, ctrl_2_va=None, events=None):
        """ See the super classes for parameter descriptions """

        Entry.__init__(self, name, hw_comp, stream, lbl_ctrl, value_ctrl)

        # TODO: can it happen value_ctrl is None and va_2_ctrl is not None?!
        if va and (value_ctrl or va_2_ctrl):
            VigilantAttributeConnector.__init__(self, va, value_ctrl, va_2_ctrl, ctrl_2_va, events)
        elif any((va_2_ctrl, ctrl_2_va, events)):
            raise ValueError("Cannot create VigilantAttributeConnector for %s, while also "
                             "receiving value getting and setting parameters!" % name)
        else:
            self.vigilattr = va  # Attribute needed, even if there's no VAC to provide it
            logging.debug("Creating empty SettingEntry without VigilantAttributeConnector")

    def pause(self):
        if hasattr(self, "va_2_ctrl") and self.va_2_ctrl:
            VigilantAttributeConnector.pause(self)

    def resume(self):
        if hasattr(self, "va_2_ctrl") and self.va_2_ctrl:
            VigilantAttributeConnector.resume(self)


class AxisSettingEntry(AxisConnector, Entry):
    """ An Axis setting linked to a Vigilant Attribute """

    def __init__(self, name, hw_comp, stream=None, lbl_ctrl=None, value_ctrl=None,
                 pos_2_ctrl=None, ctrl_2_pos=None, events=None):
        """
        :param name: (str): The name of the setting
        :param hw_comp: (HardwareComponent): The component to which the setting belongs
        :param lbl_ctrl: (wx.StaticText): The setting label
        :param value_ctrl: (wx.Window): The widget containing the current value

        See the AxisConnector class for a description of the other parameters.

        """

        Entry.__init__(self, name, hw_comp, stream, lbl_ctrl, value_ctrl)

        if None not in (name, value_ctrl):
            AxisConnector.__init__(self, name, hw_comp, value_ctrl, pos_2_ctrl, ctrl_2_pos, events)
        elif any((pos_2_ctrl, ctrl_2_pos, events)):
            logging.error("Cannot create AxisConnector")
        else:
            logging.debug("Cannot create AxisConnector")

    def pause(self):
        if hasattr(self, "pos_2_ctrl") and self.pos_2_ctrl:
            AxisConnector.pause(self)

    def resume(self):
        if hasattr(self, "pos_2_ctrl") and self.pos_2_ctrl:
            AxisConnector.resume(self)
