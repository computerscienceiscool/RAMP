# -*- coding: utf-8 -*-
"""
Created on Fri Apr 19 14:35:00 2019
This is the code for the open-source stochastic model for the generation of 
multi-energy load profiles in off-grid areas, called RAMP, v0.3.0.

@authors:
- Francesco Lombardi, Politecnico di Milano
- Sergio Balderrama, Université de Liège
- Sylvain Quoilin, KU Leuven
- Emanuela Colombo, Politecnico di Milano

Copyright 2019 RAMP, contributors listed above.
Licensed under the European Union Public Licence (EUPL), Version 1.2;
you may not use this file except in compliance with the License.

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and limitations
under the License.
"""

#%% Import required modules

import sys,os

import numpy as np

sys.path.append('../')

try:
    from .core.utils import get_day_type, yearly_pattern
    from .core.stochastic_process import stochastic_process
    from .post_process import post_process as pp
except ImportError:
    from core.utils import get_day_type, yearly_pattern
    from core.stochastic_process import stochastic_process
    from post_process import post_process as pp


def run_usecase(j=None, fname=None, ofname=None, num_profiles=None, days=None, plot=True, parallel=False):

    # Calls the stochastic process and saves the result in a list of stochastic profiles
    if days is None:
        Profiles_list = stochastic_process(j=j, fname=fname, num_profiles=num_profiles, day_type=yearly_pattern(), parallel=parallel)

        # Post-processes the results and generates plots
        Profiles_avg, Profiles_list_kW, Profiles_series = pp.Profile_formatting(Profiles_list)
        pp.Profile_series_plot(Profiles_series)  # by default, profiles are plotted as a series

        pp.export_series(Profiles_series, j, fname, ofname)

        if len(Profiles_list) > 1:  # if more than one daily profile is generated, also cloud plots are shown
            pp.Profile_cloud_plot(Profiles_list, Profiles_avg)
    else:
        Profiles_list = []
        if parallel is True:
            Profiles_list = stochastic_process(j=j, fname=fname, num_profiles=len(days), day_type=[get_day_type(day)for day in days], parallel=parallel)
        else:
            for day in days:
                print("Day", day)
                daily_profiles = stochastic_process(j=j, fname=fname, num_profiles=num_profiles, day_type=get_day_type(day), parallel=parallel)

                Profiles_list.append(np.mean(daily_profiles, axis=0))
        if plot is True:
            # Post-processes the results and generates plots
            Profiles_avg, Profiles_list_kW, Profiles_series = pp.Profile_formatting(Profiles_list)
            pp.Profile_series_plot(Profiles_series)  # by default, profiles are plotted as a series

            pp.export_series(Profiles_series, j, fname, ofname)

            if len(Profiles_list) > 1:  # if more than one daily profile is generated, also cloud plots are shown
                pp.Profile_cloud_plot(Profiles_list, Profiles_avg)
        else:
            return Profiles_list


input_files_to_run = [1, 2, 3]


if __name__ == "__main__":

    for j in input_files_to_run:
        try:
            run_usecase(j=j, fname='../example/input_file_{}.xlsx'.format(j))
        except:
            print('Input files in .xlsx format not found. Running the default files in .py format.')
            run_usecase(j=j)
            