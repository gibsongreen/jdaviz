import numpy as np
from astropy import units as u
from traitlets import List, Unicode, observe, Bool

from jdaviz.core.events import GlobalDisplayUnitChanged
from jdaviz.core.registries import tray_registry
from jdaviz.core.template_mixin import (PluginTemplateMixin, UnitSelectPluginComponent,
                                        SelectPluginComponent, PluginUserApi)
from jdaviz.core.validunits import (create_spectral_equivalencies_list,
                                    create_flux_equivalencies_list)

__all__ = ['UnitConversion']


def _valid_glue_display_unit(unit_str, sv, axis='x'):
    # need to make sure the unit string is formatted according to the list of valid choices
    # that glue will accept (may not be the same as the defaults of the installed version of
    # astropy)
    if not unit_str:
        return unit_str
    unit_u = u.Unit(unit_str)
    choices_str = getattr(sv.state.__class__, f'{axis}_display_unit').get_choices(sv.state)
    choices_str = [choice for choice in choices_str if choice is not None]
    choices_u = [u.Unit(choice) for choice in choices_str]
    if unit_u not in choices_u:
        raise ValueError(f"{unit_str} could not find match in valid {axis} display units {choices_str}")  # noqa
    ind = choices_u.index(unit_u)
    return choices_str[ind]


@tray_registry('g-unit-conversion', label="Unit Conversion",
               viewer_requirements='spectrum')
class UnitConversion(PluginTemplateMixin):
    """
    The Unit Conversion plugin handles global app-wide unit-conversion.
    See the :ref:`Unit Conversion Plugin Documentation <unit-conversion>` for more details.

    Only the following attributes and methods are available through the
    :ref:`public plugin API <plugin-apis>`:

    * :meth:`~jdaviz.core.template_mixin.PluginTemplateMixin.show`
    * :meth:`~jdaviz.core.template_mixin.PluginTemplateMixin.open_in_tray`
    * :meth:`~jdaviz.core.template_mixin.PluginTemplateMixin.close_in_tray`
    * ``spectral_unit`` (:class:`~jdaviz.core.template_mixin.SelectPluginComponent`):
      Global unit to use for all spectral axes.
    * ``flux_or_sb_unit`` (:class:`~jdaviz.core.template_mixin.SelectPluginComponent`):
      Global unit to use for all flux axes.
    """
    template_file = __file__, "unit_conversion.vue"

    spectral_unit_items = List().tag(sync=True)
    spectral_unit_selected = Unicode().tag(sync=True)

    flux_unit_items = List().tag(sync=True)
    flux_unit_selected = Unicode().tag(sync=True)

    show_translator = Bool(False).tag(sync=True)
    flux_or_sb_items = List().tag(sync=True)
    flux_or_sb_selected = Unicode().tag(sync=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.config not in ['specviz', 'cubeviz']:
            # TODO [specviz2d, mosviz] x_display_unit is not implemented in glue for image viewer
            # used by spectrum-2d-viewer
            # TODO [mosviz]: add to yaml file
            # TODO [cubeviz, slice]: slice indicator broken after changing spectral_unit
            # TODO: support for multiple viewers and handling of mixed state from glue (or does
            # this force all to sync?)
            self.disabled_msg = f'This plugin is temporarily disabled in {self.config}. Effort to improve it is being tracked at GitHub Issue 1972.'  # noqa

        # TODO [markers]: existing markers need converting
        self.spectrum_viewer.state.add_callback('x_display_unit',
                                                self._on_glue_x_display_unit_changed)
        self.spectrum_viewer.state.add_callback('y_display_unit',
                                                self._on_glue_y_display_unit_changed)

        self.spectral_unit = UnitSelectPluginComponent(self,
                                                       items='spectral_unit_items',
                                                       selected='spectral_unit_selected')
        self.flux_or_sb_unit = UnitSelectPluginComponent(self,
                                                         items='flux_unit_items',
                                                         selected='flux_unit_selected')
        self.flux_or_sb = SelectPluginComponent(self,
                                                items='flux_or_sb_items',
                                                selected='flux_or_sb_selected',
                                                manual_options=['Surface Brightness', 'Flux'])

    @property
    def user_api(self):
        return PluginUserApi(self, expose=('spectral_unit',))

    def _on_glue_x_display_unit_changed(self, x_unit):
        if x_unit is None:
            return
        if x_unit == 'deg' and self.app.config == 'cubeviz':
            # original unit during init can be deg (before axis is set correctly)
            return
        self.spectrum_viewer.set_plot_axes()
        if x_unit != self.spectral_unit.selected:
            x_unit = _valid_glue_display_unit(x_unit, self.spectrum_viewer, 'x')
            x_u = u.Unit(x_unit)
            choices = create_spectral_equivalencies_list(x_u)
            # ensure that original entry is in the list of choices
            if not np.any([x_u == u.Unit(choice) for choice in choices]):
                choices = [x_unit] + choices
            self.spectral_unit.choices = choices
            # in addition to the jdaviz options, allow the user to set any glue-valid unit
            # which would then be appended on to the list of choices going forward
            self.spectral_unit._addl_unit_strings = self.spectrum_viewer.state.__class__.x_display_unit.get_choices(self.spectrum_viewer.state)  # noqa
            self.spectral_unit.selected = x_unit
            if not len(self.flux_or_sb_unit.choices):
                # in case flux_unit was triggered first (but could not be set because there
                # as no spectral_unit to determine valid equivalencies)
                self._on_glue_y_display_unit_changed(self.spectrum_viewer.state.y_display_unit)

    def _on_glue_y_display_unit_changed(self, y_unit):
        if y_unit is None:
            return
        if self.spectral_unit.selected == "":
            # no spectral unit set yet, cannot determine equivalencies
            # setting the spectral unit will check len(flux_or_sb_unit.choices)
            # and call this manually in the case that that is triggered second.
            return
        self.spectrum_viewer.set_plot_axes()
        if y_unit != self.flux_or_sb_unit.selected:
            x_u = u.Unit(self.spectral_unit.selected)
            y_unit = _valid_glue_display_unit(y_unit, self.spectrum_viewer, 'y')
            y_u = u.Unit(y_unit)
            choices = create_flux_equivalencies_list(y_u, x_u)
            # ensure that original entry is in the list of choices
            if not np.any([y_u == u.Unit(choice) for choice in choices]):
                choices = [y_unit] + choices
            self.flux_or_sb_unit.choices = choices
            self.flux_or_sb_unit.selected = y_unit

    def translate_units(self, flux_or_sb_selected):
        spec_units = u.Unit(self.spectrum_viewer.state.y_display_unit)
        print('spec units ', spec_units, '  f or sb ', flux_or_sb_selected)
        # Surface Brightness -> Flux
        if u.sr in spec_units.bases and flux_or_sb_selected == 'Flux':
            spec_units *= u.sr
            # update display units
            self.spectrum_viewer.state.y_display_unit = str(spec_units)

        # Flux -> Surface Brightness
        elif u.sr not in spec_units.bases and flux_or_sb_selected == 'Surface Brightness':
            spec_units /= u.sr
            # update display units
            self.spectrum_viewer.state.y_display_unit = str(spec_units)

    @observe('spectral_unit_selected')
    def _on_spectral_unit_changed(self, *args):
        xunit = _valid_glue_display_unit(self.spectral_unit.selected, self.spectrum_viewer, 'x')
        if self.spectrum_viewer.state.x_display_unit != xunit:
            self.spectrum_viewer.state.x_display_unit = xunit
            self.hub.broadcast(GlobalDisplayUnitChanged('spectral',
                               self.spectral_unit.selected,
                               sender=self))

    @observe('flux_unit_selected')
    def _on_flux_unit_changed(self, *args):
        yunit = _valid_glue_display_unit(self.flux_or_sb_unit.selected, self.spectrum_viewer, 'y')
        if self.spectrum_viewer.state.y_display_unit != yunit:
            self.spectrum_viewer.state.y_display_unit = yunit
            self.hub.broadcast(GlobalDisplayUnitChanged('flux',
                                                        self.flux_or_sb_unit.selected,
                                                        sender=self))

    # Ensure first dropdown selection for Flux/Surface Brightness
    # is in accordance with the data collection item's units.
    @observe('show_translator')
    def _set_flux_or_sb(self, *args):
        if (self.spectrum_viewer and hasattr(self.spectrum_viewer.state, 'y_display_unit')
           and self.spectrum_viewer.state.y_display_unit is not None):
            if u.sr in u.Unit(self.spectrum_viewer.state.y_display_unit).bases:
                self.flux_or_sb_selected = 'Surface Brightness'
            else:
                self.flux_or_sb_selected = 'Flux'

    @observe('flux_or_sb_selected')
    def _translate(self, *args):
        # currently unsupported, can be supported with a scale factor
        if self.app.config == 'specviz':
            return

        # Check for a scale factor/data passed through spectral extraction plugin.
        specs_w_factor = [spec for spec in self.app.data_collection
                          if "_pixel_scale_factor" in spec.meta]
        # Translate if we have a scale factor
        if specs_w_factor:
            self.translate_units(self.flux_or_sb_selected)
        # The translator dropdown hasn't been loaded yet so don't try translating
        elif not self.show_translator:
            return
        # Notify the user to extract a spectrum before using the surface brightness/flux
        # translation. Can be removed after all 1D spectra in Cubeviz pass through
        # spectral extraction plugin (as the scale factor will then be stored).
        else:
            raise ValueError("No collapsed spectra in data collection, \
                              please collapse a spectrum first.")
