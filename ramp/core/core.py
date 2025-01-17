# -*- coding: utf-8 -*-
"""
The code is based on UseCase, User and Appliance classes.
A UseCase instance consists of a list of User instances which own Appliance instances
Within the Appliance class, some other functions are created to define windows of use and,
if needed, specific duty cycles
"""
import numpy as np
import pandas as pd
from tqdm import tqdm
import multiprocessing
import warnings
import random
import math
from ramp.core.constants import NEW_TO_OLD_MAPPING, APPLIANCE_ATTRIBUTES, APPLIANCE_ARGS, WINDOWS_PARAMETERS, DUTY_CYCLE_PARAMETERS, switch_on_parameters
from ramp.core.utils import random_variation, duty_cycle, random_choice, read_input_file, within_peak_time_window


from typing import List, Union,Iterable
from ramp.errors_logs.errors import InvalidType,InvalidWindow

def single_appliance_daily_load_profile(args):
    app, args = args
    app.generate_load_profile(*args, power=app.power[args[0]])

    return args[0], app.daily_use


class UseCase:
    def __init__(self, name:str="", users:Union[List,None]=None):
        """ Creates a UseCase instance for gathering a list of User instances which own Appliance instances

        Parameters
        ----------
        name : str, optional
            name of the usecase instance, by default ""
        users : Union[Iterable,None], optional
            a list of users to be added to the usecase instance, by default None
        """
        self.name = name
        self.appliances = []
        if users is None:
            users = []
        self.users = users
        self.collect_appliances_from_users()

    def add_user(self, user) -> None:
        """adds new user to the user property list

        Parameters
        ----------
        user : User
            an user instance

        Raises
        ------
        InvalidType
            any type rather than User will raise the error.
        """
        if isinstance(user, User):
            self.users.append(user)
        else:
            raise InvalidType(f"{type(user)} is not valid. Only 'User' type is acceptable.")

    def collect_appliances_from_users(self):
        appliances = []
        for user in self.users:
            appliances = appliances + user.App_list
        self.appliances = appliances


    def generate_daily_load_profiles(self, num_profiles, peak_time_range, day_types):
        profiles = []
        for prof_i in range(num_profiles):
            # initialise an empty daily profile (or profile load)
            # that will be filled with the sum of the daily profiles of each User instance
            usecase_load = np.zeros(1440)
            # for each User instance generate a load profile, iterating through all user of this instance and
            # all appliances they own, corresponds to step 2. of [1], p.7
            for user in self.users:
                user.generate_aggregated_load_profile(prof_i, peak_time_range, day_types)
                # aggregate the user load to the usecase load
                usecase_load = usecase_load + user.load
            profiles.append(usecase_load)
            # screen update about progress of computation
            #print('Profile', prof_i+1, '/', num_profiles, 'completed')
        return profiles

    def generate_daily_load_profiles_parallel(self, num_profiles, peak_time_range, day_types):
        max_parallel_processes = multiprocessing.cpu_count()
        tasks = []
        t = 0
        for day_id in range(num_profiles):
            day_type = day_types[day_id]
            for user in self.users:
                for app in user.App_list:
                    for _ in range(user.num_users):
                        t = t + 1
                        tasks.append((app, (day_id, peak_time_range, day_type)))

        daily_profiles_dict = {}
        timeout = 1

        with multiprocessing.Pool(max_parallel_processes) as pool:
            with tqdm(
                    total=len(tasks),
                    desc=f"Computing appliances profiles",
                    unit="unit",
            ) as pbar:

                imap_unordered_it = pool.imap_unordered(single_appliance_daily_load_profile, tasks, chunksize=4)
                for prof_i, daily_load in imap_unordered_it:
                    if prof_i in daily_profiles_dict:
                        daily_profiles_dict[prof_i].append(daily_load)
                    else:
                        daily_profiles_dict[prof_i] = [daily_load]
                    pbar.update()

            daily_profiles = np.zeros((num_profiles, 1440))

            for day_id in range(num_profiles):
                daily_profiles[day_id, :] = np.vstack(daily_profiles_dict[day_id]).sum(axis=0)

        return daily_profiles

    def save(self, filename:str=None) -> Union[pd.DataFrame,None]:
        """Saves/returns the model databas including all the users and their appliances as a single pd.DataFrame or excel file.

        Parameters
        ----------
        filename : str, optional
            The path where the data will be stored. if None, function will return a pd.DataFrame, by default None.

        Returns
        -------
        Union[pd.DataFrame,None]
            if filename is passed, returnes None, otherwise will return a pd.DataFrame

        Notes
        -------
        The 'filename' parameter should consist the path and the name of the file without the file extension.
        For example, if the user wants to save database into "new_folder" directory and name the file as "ramp_database.xlsx" should use:

        .. code-block:: python

            usecase.save("new_folder/ramp_database")
        """
        answer = pd.concat([user.save() for user in self.users], ignore_index=True)
        if filename is not None:
            answer.to_excel(f"{filename}.xlsx", index=False, engine="openpyxl")
        else:
            return answer

    def export_to_dataframe(self) -> pd.DataFrame:
        """exports the model database to a pd.DataFrame containing all the data related to users and their appliances

        Returns
        -------
        pd.DataFrame
            the model database
        """
        return self.save()

    def load(self, filename:str) -> None:
        """Open an .xlsx file which was produced via the save method and create instances of Users and Appliances

        Parameters
        ----------
        filename : str
            The path where the excel database is.

        Raises
        ---------
        ValueError
            #. if the 'num_users' is not the same for a given user profile
            #. if the 'user_preference' is not the same for a given user profile

        Note
        ------
        The 'filename' parameter should consist the path and the name of the file with the file extension.
        For example, if the user wants to save database into "new_folder" directory and name the file as "ramp_database.xlsx" should use:

        .. code-block:: python

            usecase.save("new_folder/ramp_database.xlsx")
        """

        df = read_input_file(filename=filename)
        for user_name in df.user_name.unique():
            user_df = df.loc[df.user_name == user_name]
            num_users = user_df.num_users.unique()
            if len(num_users) == 1:
                num_users = num_users[0]
            else:
                raise ValueError(
                    "'num_users' should be the same for a given user profile"
                )
            user_preference = user_df.user_preference.unique()
            if len(user_preference) == 1:
                user_preference = user_preference[0]
            else:
                raise ValueError(
                    "'user_preference' should be the same for a given user profile"
                )

            # create user and add it to usecase
            user = User(user_name, num_users, user_preference)
            self.add_user(user)
            # itereate through the lines of the DataFrame, each line representing one Appliance instance
            for row in user_df.loc[
                :, ~user_df.columns.isin(["user_name", "num_users", "user_preference"])
            ].to_dict(orient="records"):
                # assign Appliance arguments
                appliance_parameters = {k: row[k] for k in APPLIANCE_ARGS}

                # assign windows arguments
                for k in WINDOWS_PARAMETERS:
                    if "window" in k:
                        w_start = row.get(k + "_start", np.NaN)
                        w_end = row.get(k + "_end", np.NaN)
                        if not np.isnan(w_start) and not np.isnan(w_end):
                            appliance_parameters[k] = np.array(
                                [w_start, w_end], dtype=np.intc
                            )
                    else:
                        val = row.get(k, np.NaN)
                        if not np.isnan(val):
                            appliance_parameters[k] = val

                # assign duty cycles arguments
                for duty_cycle_params in DUTY_CYCLE_PARAMETERS:
                    for k in duty_cycle_params:
                        if "cw" in k:
                            cw_start = row.get(k + "_start", np.NaN)
                            cw_end = row.get(k + "_end", np.NaN)
                            if not np.isnan(cw_start) and not np.isnan(cw_end):
                                appliance_parameters[k] = np.array(
                                    [cw_start, cw_end], dtype=np.intc
                                )
                        else:
                            val = row.get(k, np.NaN)
                            if not np.isnan(val):
                                appliance_parameters[k] = val

                user.add_appliance(**appliance_parameters)

        self.collect_appliances_from_users()





class User:
    def __init__(self, user_name:str="", num_users:int=1, user_preference:int=0):
        """Creates a User instance (User Category)

        Parameters
        ----------
        user_name : str, optional
            name of the user type, by default ""
        num_users : int, optional
            number of users within the resprective user-type, by default 1
        user_preference : int {0,1,2,3}, optional
            Related to cooking behaviour, how many types of meal a user wants a day (number of user preferences has to be defined here and will be further specified with pref_index parameter), by default 0
        """
        self.user_name = user_name
        self.num_users = num_users
        self.user_preference = user_preference
        self.load = None
        self.App_list = []  # each instance of User (i.e. each user class) has its own list of Appliances

    def __repr__(self):
        return self.save()[["user_name","num_users","name","number","power"]].to_string()

    def add_appliance(self, *args, **kwargs):
        """adds an appliance to the user category with all the appliance characteristics in a single function


        Returns
        -------
        Appliance
            returns the appliance instance
        """

        # parse the args into the kwargs
        if len(args) > 0:
            for a_name, a_val in zip(APPLIANCE_ARGS, args):
                kwargs[a_name] = a_val

        # collects windows arguments
        windows_args = {}
        for k in WINDOWS_PARAMETERS:
            if k in kwargs:
                windows_args[k] = kwargs.pop(k)

        # collects duty cycles arguments
        duty_cycle_parameters = {}
        for i, duty_cycle_params in enumerate(DUTY_CYCLE_PARAMETERS):
            cycle_parameters = {}
            for k in duty_cycle_params:
                if k in kwargs:
                    cycle_parameters[k] = kwargs.pop(k)
            if cycle_parameters:
                duty_cycle_parameters[i+1] = cycle_parameters

        app = Appliance(self, **kwargs)

        if windows_args:
            app.windows(**windows_args)
        for i in duty_cycle_parameters:
            app.specific_cycle(i, **duty_cycle_parameters[i])

        return app

    @property
    def maximum_profile(self) -> np.array:
        """Aggregate the theoretical maximal profiles of each appliance of the user by switching the appliance always on

        Returns
        --------
        np.array
        """
        user_max_profile = np.zeros(1440)
        for appliance in self.App_list:
            # Calculate windows curve, i.e. the theoretical maximum curve that can be obtained, for each app, by switching-on always all the 'n' apps altogether in any time-step of the functioning windows
            app_max_profile = appliance.maximum_profile  # this computes the curve for the specific App
            user_max_profile = np.vstack([user_max_profile, app_max_profile])  # this stacks the specific App curve in an overall curve comprising all the Apps within a User class
        return np.transpose(np.sum(user_max_profile, axis=0)) * self.num_users

    def save(self, filename:str=None) -> Union[pd.DataFrame,None]:
        """Saves/returns the model databas including allappliances as a single pd.DataFrame or excel file.

        Parameters
        ----------
        filename : str, optional
            The path where the data will be stored. if None, function will return a pd.DataFrame, by default None.

        Returns
        -------
        Union[pd.DataFrame,None]
            if filename is passed, returnes None, otherwise will return a pd.DataFrame

        Raises
        ------
        Exception
            if now appliaces is assigned to the user and the function is called.

        Notes
        -------
        1. The 'filename' parameter should consist the path and the name of the file without the file extension.
        For example, if the user wants to save database into "new_folder" directory and name the file as "ramp_database.xlsx" should use:

        .. code-block:: python

            user.save("new_folder/ramp_database")

        2. Appliances are added to the user-type only if **'windows'** method of the Appliance is called.
        """

        try:
            answer = pd.concat([app.save() for app in self.App_list], ignore_index=True)
        except ValueError:
            raise Exception("No appliances is assigned to the user.")

        if filename is not None:
            answer.to_excel(f"{filename}.xlsx", engine="openpyxl")
        else:
            return answer

    def __eq__(self, other_user):
        """Compare two users

        ensure they have the same properties
        ensure they have the same appliances
        """
        answer = np.array([])
        for attribute in ("user_name", "num_users", "user_preference"):
            if hasattr(self, attribute) and hasattr(other_user, attribute):
                np.append(
                    answer, [getattr(self, attribute) == getattr(other_user, attribute)]
                )
            else:
                print(f"Problem with {attribute} of user")
                np.append(answer, False)
        answer = answer.all()

        if answer is True:
            # user attributes match, continue to compare each appliance
            if len(self.App_list) == len(other_user.App_list):
                answer = np.array([])
                for my_appliance, their_appliance in zip(
                    self.App_list, other_user.App_list
                ):
                    temp = my_appliance == their_appliance
                    answer = np.append(answer, temp)
                if len(answer) > 0:
                    answer = answer.all()
                else:

                    if len(self.App_list) > 0:
                        answer = False
                    else:
                        # both users have no appliances
                        answer = True
            else:
                print(
                    f"The user {self.user_name} and {other_user.user_name} do not have the same number of appliances"
                )
                answer = False
        return answer

    def export_to_dataframe(self) -> pd.DataFrame:
        """Saves/returns the model databas including allappliances as a single pd.DataFrame or excel file.

        Returns
        -------
        pd.DataFrame
            if filename is passed, returnes None, otherwise will return a pd.DataFrame

        Raises
        ------
        Exception
            if now appliaces is assigned to the user and the function is called.

        Notes
        -------
        Appliances are added to the user-type only if **'windows'** method of the Appliance is called.
        """
        return self.save()


    def Appliance(
        self,
        number=1,
        power=0,
        num_windows=1,
        func_time=0,
        time_fraction_random_variability=0,
        func_cycle=1,
        fixed="no",
        fixed_cycle=0,
        occasional_use=1,
        flat="no",
        thermal_P_var=0,
        pref_index=0,
        wd_we_type=2,
        name="",
    ):
        """Back-compatibility with legacy code

        Notes
        ------
        refer to Appliance class docs
        """
        return self.add_appliance(
            number=number,
            power=power,
            num_windows=num_windows,
            func_time=func_time,
            time_fraction_random_variability=time_fraction_random_variability,
            func_cycle=func_cycle,
            fixed=fixed,
            fixed_cycle=fixed_cycle,
            occasional_use=occasional_use,
            flat=flat,
            thermal_p_var=thermal_P_var,
            pref_index=pref_index,
            wd_we_type=wd_we_type,
            name=name,
        )

    def generate_single_load_profile(self, prof_i:int, peak_time_range:np.array, day_type:int):
        """Generates a load profile for a single user taking all its appliances into consideration

        Parameters
        ----------
        prof_i: int[0,365]
            ith profile (day) requested by the user. 0 is the first day of the year and 364 is the last day.

        peak_time_range: np.array
            randomised peak time range calculated using calc_peak_time_range function.

        day_type: int[0,1]
            type of the ith profile. 0 for a week day or 1 for a weekend day

        Returns
        --------
        np.array
            load profile for the requested day
        """

        if prof_i not in range(365):
            raise ValueError(f'prof_i should be an integer in range of 0 to 364')

        single_load = np.zeros(1440)


        for App in self.App_list:  # iterates for all the App types in the given User class

            App.generate_load_profile(prof_i, peak_time_range, day_type, power=App.power[prof_i])

            single_load = single_load + App.daily_use  # adds the Appliance load profile to the single User load profile
        return single_load

    def generate_aggregated_load_profile(self, prof_i, peak_time_range, day_type):
        """Generates an aggregated load profile from single load profile of each user


        Parameters
        ----------

        prof_i: int[0,365]
            ith profile (day) requested by the user. 0 is the first day of the year and 364 is the last day.
        peak_time_range: numpy array
            randomised peak time range calculated using calc_peak_time_range function
        day_type: int[0,1]
            type of the ith profile. 0 for a week day or 1 for a weekend day

        Returns
        --------
        np.array
            load profile for the requested day

        Notes
        ------
        Each single load profile has its own separate randomisation
        """

        if prof_i not in range(365):
            raise ValueError(f'prof_i should be an integer in range of 0 to 364')


        self.load = np.zeros(1440)  # initialise empty load for User instance
        for _ in range(self.num_users):
            # iterates for every single user within a User class.
            self.load = self.load + self.generate_single_load_profile(prof_i, peak_time_range, day_type)

        return self.load

class Appliance:
    def __init__(
        self,
        user,
        number:int=1,
        power:Union[float,pd.DataFrame]=0,
        num_windows:int=1,
        func_time:int=0,
        time_fraction_random_variability:float=0,
        func_cycle:int=1,
        fixed:str="no",
        fixed_cycle:int=0,
        occasional_use:float=1,
        flat:str="no",
        thermal_p_var:int=0,
        pref_index:int=0,
        wd_we_type:int=2,
        name:str="",
    ):
        """Creates an appliance for a given user

        Parameters
        ----------
        user : ramp.User
            user to which the appliance is bounded

        number : int, optional
            number of appliances of the specified kind, by default 1

        power : Union[float.pd.DataFrame], optional
            Power rating of appliance (average). If the appliance has variant daily power, a series (with the size of 365) can be passed., by default 0

        num_windows : int [1,2,3], optional
            Number of distinct time windows, by default 1

        func_time : int[0,1440], optional
            total time (minutes) the appliance is on during the day (not dependant on windows). Acceptable values are in range 0 to 1440, by default 0

        time_fraction_random_variability : Percentage, optional
            percentage of total time of use that is subject to random variability. For time (not for windows), randomizes the total time the appliance is on, by default 0

        func_cycle : int[0,1440], optional
            minimum time(minutes) the appliance is kept on after switch-on event, by default 1

        fixed : str, optional
            if 'yes', all the 'n' appliances of this kind are always switched-on together, by default "no"

        fixed_cycle : int{0,1,2,3,4}, optional
            Number of duty cycle, 0 means continuous power, if not 0 you have to fill the cw (cycle window) parameter (you may define up to 3 cws), by default 0

        occasional_use : Percentage, optional
            Defines how often the appliance is used, e.g. every second day will be 0.5, by default 1

        flat : str{'yes','no'}, optional
            allows to model appliances that are not subject to any kind of random variability, such as public lighting, by default "no"

        thermal_p_var : Percentage, optional
            Range of change of the power of the appliance (e.g. shower not taken at same temparature) or for the power of duty cycles (e.g. for a cooker, AC, heater if external temperature is different…), by default 0

        pref_index : int{0,1,2,3}, optional
            defines preference index for association with random User daily preference behaviour.This number must be smaller or equal to the value input in user_preference, by default 0

        wd_we_type : int{0,1,2}, optional
            Specify whether the appliance is used only on weekdays (0), weekend (1) or the whole week (2), by default 2

        name : str, optional
            the name of the appliance, by default ""

        Raises
        --------
        ValueError
            1. if power is not passed as a number of series.
            2. power array size is not (365,1)
        """

        self.user = user
        self.name = name
        self.number = number
        self.num_windows = num_windows
        self.func_time = func_time
        self.time_fraction_random_variability = time_fraction_random_variability
        self.func_cycle = (
            func_cycle
        )
        self.fixed = fixed
        self.fixed_cycle = fixed_cycle
        self.occasional_use = occasional_use
        self.flat = flat
        self.thermal_p_var = (
            thermal_p_var
        )
        self.pref_index = pref_index
        self.wd_we_type = wd_we_type

        if isinstance(power,pd.DataFrame):
            if power.shape == (365,1):
                power = power.values[:,0]
            else:
                raise ValueError("wrong size of array. array size should be (365,1).")

        elif isinstance(power,str):
            power = pd.read_json(power).values[:,0]

        elif isinstance(power,(float,int)):
            # TODO change this automatic value depending on the range of the usecase
            power = power * np.ones(366)

        else:
            raise ValueError("wrong data type for power.")

        self.power = power

        # attributes initialized by self.windows
        self.random_var_w = 0
        self.window_1 = np.array([0, 0])
        self.window_2 = np.array([0, 0])
        self.window_3 = np.array([0, 0])
        self.random_var_1 = 0
        self.random_var_2 = 0
        self.random_var_3 = 0
        self.daily_use = None
        self.free_spots = None

        # attributes used for specific fixed and random cycles
        self.p_11 = 0
        self.p_12 = 0
        self.t_11 = 0
        self.t_12 = 0
        self.r_c1 = 0
        self.p_21 = 0
        self.p_22 = 0
        self.t_21 = 0
        self.t_22 = 0
        self.r_c2 = 0
        self.p_31 = 0
        self.p_32 = 0
        self.t_31 = 0
        self.t_32 = 0
        self.r_c3 = 0

        # attribute used for cycle_behaviour
        self.cw11 = np.array([0, 0])
        self.cw12 = np.array([0, 0])
        self.cw21 = np.array([0, 0])
        self.cw22 = np.array([0, 0])
        self.cw31 = np.array([0, 0])
        self.cw32 = np.array([0, 0])

        self.random_cycle1 = np.array([])
        self.random_cycle2 = np.array([])
        self.random_cycle3 = np.array([])

    def save(self) -> pd.DataFrame:
        """returns a pd.DataFrame containing the appliance data

        Returns
        -------
        pd.DataFrame
            includes all the attributes and the user related information of an appliance.
        """
        dm = {}
        for user_attribute in ("user_name", "num_users", "user_preference"):
            dm[user_attribute] = getattr(self.user, user_attribute)
        for attribute in APPLIANCE_ATTRIBUTES:

            if hasattr(self, attribute):
                if "window_" in attribute or "cw" in attribute:
                    window_value = getattr(self, attribute)
                    dm[attribute + "_start"] = window_value[0]
                    dm[attribute + "_end"] = window_value[1]
                elif attribute == "power":
                    power_values = getattr(self, attribute)
                    if np.diff(power_values).sum() == 0:
                        power_values = power_values[0]
                    else:
                        power_values = power_values.tolist()
                    dm[attribute] = power_values
                else:
                    dm[attribute] = getattr(self, attribute)
            else:
                # this is for legacy purpose, so that people can export their old models to new format
                old_attribute = NEW_TO_OLD_MAPPING.get(attribute,attribute)
                if hasattr(self, old_attribute):
                    if "window_" in attribute or "cw" in attribute:
                        window_value = getattr(self, old_attribute)
                        dm[attribute + "_start"] = window_value[0]
                        dm[attribute + "_end"] = window_value[1]
                    elif old_attribute == "POWER":
                        power_values = getattr(self, old_attribute)
                        if np.diff(power_values).sum() == 0:
                            power_values = power_values[0]
                        else:
                            power_values = power_values.tolist()
                        dm[attribute] = power_values
                    else:
                        dm[attribute] = getattr(self, old_attribute)
                else:
                    if "cw" in old_attribute:
                        dm[attribute + "_start"] = None
                        dm[attribute + "_end"] = None
                    else:
                        dm[attribute] = None
        return pd.DataFrame.from_records([dm])

    def export_to_dataframe(self) -> pd.DataFrame:
        """returns a pd.DataFrame containing the appliance data

        Returns
        -------
        pd.DataFrame
            includes all the attributes and the user related information of an appliance.
        """
        return self.save()

    def __repr__(self):

        try:
            return self.save()[["user_name","num_users","name","number","power"]].to_string()
        except Exception:
            return ""


    def __eq__(self, other_appliance) -> bool:
        """checks the equality of two appliances

        Returns
        -------
        bool
            True if the two appliances:
                1. have the same attributes
                2. all their attributes have the same value
        """
        answer = np.array([])
        for attribute in APPLIANCE_ATTRIBUTES:
            if hasattr(self, attribute) and hasattr(other_appliance, attribute):
                np.append(
                    answer,
                    [getattr(self, attribute) == getattr(other_appliance, attribute)],
                )
            elif (
                hasattr(self, attribute) is False
                and hasattr(other_appliance, attribute) is False
            ):
                np.append(answer, True)
            else:
                if hasattr(self, attribute) is False:
                    print(f"{attribute} of appliance {self.name} is not assigned")
                else:
                    print(
                        f"{attribute} of appliance {other_appliance.name} is not assigned"
                    )
                np.append(answer, False)
        return answer.all()

    def windows(self, window_1:Iterable=None, window_2:Iterable=None,random_var_w:float=0 ,window_3:Iterable=None):
        """assings functioning windows to the appliance and adds the appliance to the user class

        Parameters
        ----------
        window_1 : Iterable, optional
            First functioning window, by default None

        window_2 : Iterable, optional
            Second functioning window, by default None

        window_3 : Iterable, optional
            Third functioning window, by default None

        random_var_w : Percentage, optional
            variability of the windows in percent, the same for all windows, by default 0

        Raises
        ------
        InvalidWindow

            * If number of specifies windows does not correspond to the given functioning windows.
            * If the sum of all windows time intervals for the appliance is smaller than the time the appliance is supposed to be on.

        Example
        --------
        If three time window is specified for the appliance as follow:

        #. from 00:00:00 to 00:20:00
        #. from 00:30:00 to 00:35:00
        #. from 00:40:00 to 00:55:00

        .. code-block:: python

            user.windows(
                window_1 = [0,20],
                window_2 = [30,35],
                window_3 = [40,55]
            )
        """

        if window_1 is None:
            warnings.warn(UserWarning("No windows is declared, default window of 24 hours is selected"))
            self.window_1 = np.array([0, 1440])
        else:
            self.window_1 = window_1

        if window_2 is None:
            if self.num_windows >= 2:
                raise InvalidWindow("Windows 2 is not provided although 2 windows were declared")
        else:
            self.window_2 = window_2

        if window_3 is None:
            if self.num_windows == 3:
                raise InvalidWindow("Windows 3 is not provided although 3 windows were declared")
        else:
            self.window_3 = window_3

        # check that the time allocated by the windows is larger or equal to the func_time of the appliance
        window_time = 0
        for i in range(1, self.num_windows + 1, 1):
            window_time = window_time + np.diff(getattr(self, f"window_{i}"))[0]
        if window_time < self.func_time:
            raise InvalidWindow(f"The sum of all windows time intervals for the appliance '{self.name}' of user '{self.user.user_name}' is smaller than the time the appliance is supposed to be on ({window_time} < {self.func_time}). Please check your input file for typos.")

        self.random_var_w = random_var_w
        self.daily_use = np.zeros(1440) #create an empty daily use profile
        self.daily_use[self.window_1[0]:(self.window_1[1])] = np.full(np.diff(self.window_1),0.001) #fills the daily use profile with infinitesimal values that are just used to identify the functioning windows
        self.daily_use[self.window_2[0]:(self.window_2[1])] = np.full(np.diff(self.window_2),0.001) #same as above for window2
        self.daily_use[self.window_3[0]:(self.window_3[1])] = np.full(np.diff(self.window_3),0.001) #same as above for window3

        self.random_var_1 = int(random_var_w*np.diff(self.window_1)) #calculate the random variability of window1, i.e. the maximum range of time they can be enlarged or shortened
        self.random_var_2 = int(random_var_w*np.diff(self.window_2)) #same as above
        self.random_var_3 = int(random_var_w*np.diff(self.window_3)) #same as above
        self.user.App_list.append(self) #automatically appends the appliance to the user's appliance list

        if self.fixed_cycle == 1:
            self.cw11 = self.window_1
            self.cw12 = self.window_2

    def assign_random_cycles(self):
        """
        Calculates randomised cycles taking the random variability in the duty cycle duration
        """
        if self.fixed_cycle >= 1:
            p_11 = random_variation(var=self.thermal_p_var, norm=self.p_11) #randomly variates the power of thermal apps, otherwise variability is 0
            p_12 = random_variation(var=self.thermal_p_var, norm=self.p_12) #randomly variates the power of thermal apps, otherwise variability is 0
            self.random_cycle1 = duty_cycle(var=self.r_c1, t1=self.t_11, p1=p_11, t2=self.t_12, p2=p_12) #randomise also the fixed cycle
            self.random_cycle2 = self.random_cycle1
            self.random_cycle3 = self.random_cycle1
            if self.fixed_cycle >= 2:
                p_21 = random_variation(var=self.thermal_p_var, norm=self.p_21) #randomly variates the power of thermal apps, otherwise variability is 0
                p_22 = random_variation(var=self.thermal_p_var, norm=self.p_22) #randomly variates the power of thermal apps, otherwise variability is 0
                self.random_cycle2 = duty_cycle(var=self.r_c2, t1=self.t_21, p1=p_21, t2=self.t_22, p2=p_22) #randomise also the fixed cycle

                if self.fixed_cycle >= 3:
                    p_31 = random_variation(var=self.thermal_p_var, norm=self.p_31) #randomly variates the power of thermal apps, otherwise variability is 0
                    p_32 = random_variation(var=self.thermal_p_var, norm=self.p_32) #randomly variates the power of thermal apps, otherwise variability is 0
                    self.random_cycle1 = random_choice(self.r_c1, t1=self.t_11, p1=p_11, t2=self.t_12, p2=p_12)

                    self.random_cycle2 = random_choice(self.r_c2, t1=self.t_21, p1=p_21, t2=self.t_22, p2=p_22)

                    self.random_cycle3 = random_choice(self.r_c3, t1=self.t_31, p1=p_31, t2=self.t_32, p2=p_32)

    def update_available_time_for_switch_on_events(self, indexes):
        """Remove the given time indexes from the ranges available to switch appliance on

        Parameters
        ----------
        indexes: list of int
            time indexes of the daily profile concerned by a new switch-on event

        Return
        ------
        nothing but can modify self.free_spots
        """
        # identify which of the unallocated time ranges contain the switch-on event
        spot_idx = None
        for i, fs in enumerate(self.free_spots):
            if indexes[0] >= fs.start and indexes[-1] <= fs.stop:
                spot_idx = i
                break
        if spot_idx is not None:
            spot_to_split = self.free_spots.pop(spot_idx)

            if indexes[0] == spot_to_split.start and indexes[-1] == spot_to_split.stop:
                pass  # nothing to do as the whole range should be removed, which is already the case from line above
            elif indexes[0] == spot_to_split.start:
                # reinsert a range going from end of indexes up to the end of picked range
                self.free_spots.insert(spot_idx, slice(indexes[-1] + 1, spot_to_split.stop, None))
            elif indexes[-1] == spot_to_split.stop:
                # reinsert a range going from beginning of picked range up to the beginning of indexes
                self.free_spots.insert(spot_idx, slice(spot_to_split.start, indexes[0], None))
            else:
                # split the range into 2 smaller ranges
                new_spot1 = slice(spot_to_split.start, indexes[0], None)
                new_spot2 = slice(indexes[-1] + 1, spot_to_split.stop, None)

                self.free_spots.insert(spot_idx, new_spot2)
                self.free_spots.insert(spot_idx, new_spot1)

    def update_daily_use(self, coincidence, power, indexes):
        """Update the daily use depending on existence of duty cycles of the Appliance instance

        This corresponds to step 2d. and 2e. of [1]

        [1] F. Lombardi, S. Balderrama, S. Quoilin, E. Colombo,
            Generating high-resolution multi-energy load profiles for remote areas with an open-source stochastic model,
            Energy, 2019, https://doi.org/10.1016/j.energy.2019.04.097.

        """

        if self.fixed_cycle > 0:  # evaluates if the app has some duty cycles to be considered
            evaluate = np.round(np.mean(indexes)) if indexes.size > 0 else 0
            # selects the proper duty cycle and puts the corresponding power values in the indexes range
            if evaluate in range(self.cw11[0], self.cw11[1]) or evaluate in range(self.cw12[0], self.cw12[1]):
                np.put(self.daily_use, indexes, (self.random_cycle1 * coincidence))
            elif evaluate in range(self.cw21[0], self.cw21[1]) or evaluate in range(self.cw22[0], self.cw22[1]):
                np.put(self.daily_use, indexes, (self.random_cycle2 * coincidence))
            else:
                np.put(self.daily_use, indexes, (self.random_cycle3 * coincidence))
        else:  # if no duty cycles are specified, a regular switch_on event is modelled
            # randomises also the App Power if thermal_p_var is on
            np.put(self.daily_use, indexes, (random_variation(var=self.thermal_p_var, norm=coincidence * power)))
        # updates the time ranges remaining for switch on events, excluding the current switch_on event
        self.update_available_time_for_switch_on_events(indexes)

    def calc_rand_window(self, window_idx=1, window_range_limits=[0, 1440]):
        _window = self.__getattribute__(f'window_{window_idx}')
        _random_var = self.__getattribute__(f'random_var_{window_idx}')
        rand_window = [random.randint(_window[0] - _random_var, _window[0] + _random_var),
                                random.randint(_window[1] - _random_var, _window[1] + _random_var)]
        if rand_window[0] < window_range_limits[0]:
            rand_window[0] = window_range_limits[0]
        if rand_window[1] > window_range_limits[1]:
            rand_window[1] = window_range_limits[1]

        return rand_window

    @property
    def maximum_profile(self):
        """Virtual maximum load profile of the appliance

        Returns
        --------
        np.array
            It assumes the appliance is always switched-on with maximum power and
            numerosity during all of its potential windows of use
        """
        return self.daily_use * np.mean(self.power) * self.number

    def specific_cycle(self, cycle_num, **kwargs):
        """assigining specific duty cycle for the appliace (maximum of three cycles can be assigned)

        Parameters
        ----------
        cycle_num : int
            represents the number of the specific cycle to be assigned. acceptable values are [1,2,3]

        **kwargs :
            additional features passed tp each specific cycle function. For example iff cycle_num = 1, **kwargs represents the arguments of function 'spefici_cycle_1' which are:
                * p_11
                * t_11
                * p_12
                * t_12
                * r_c1
                * cw11
                * cw12
        """
        if cycle_num == 1:
            self.specific_cycle_1(**kwargs)
        elif cycle_num == 2:
            self.specific_cycle_2(**kwargs)
        elif cycle_num == 3:
            self.specific_cycle_3(**kwargs)

    def specific_cycle_1(self, p_11 = 0, t_11 = 0, p_12 = 0, t_12 = 0, r_c1 = 0, cw11=None, cw12=None):
        """assigining the frist specific duty cycle for the appliace (maximum of three cycles can be assigned)

        Parameters
        ----------
        p_11 : float, optional
            Power rating for first part of first duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_11 : int[0,1440], optional
            Duration (minutes) of first part of first duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        p_12 : int, float, optional
            Power rating for second part of first duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_12 : int[0,1440], optional
            Duration (minutes) of second part of first duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        r_c1 : Percentage [0,1], optional
            randomization of the duty cycle parts duration. There will be a uniform random variation around t_i1 and t_i2. If this parameter is set to 0.1, then t_i1 and t_i2 will be randomly reassigned between 90% and 110% of their initial value; 0 means no randomisation, by default 0

        cw11 : Iterable, optional
            Window time range for the first part of first duty cycle number (not neccessarily linked to the overall time window), by default None

        cw12 : Iterable, optional
            Window time range for the first part of first duty cycle number (not neccessarily linked to the overall time window), by default None, by default None
        """
        self.p_11 = p_11
        self.t_11 = int(t_11)
        self.p_12 = p_12
        self.t_12 = int(t_12)
        self.r_c1 = r_c1
        if cw11 is not None:
            self.cw11 = cw11
        if cw12 is not None:
            self.cw12 = cw12
        # Below is not used
        self.fixed_cycle1 = np.concatenate(((np.ones(self.t_11)*p_11),(np.ones(self.t_12)*p_12))) #create numpy array representing the duty cycle

    def specific_cycle_2(self, p_21 = 0, t_21 = 0, p_22 = 0, t_22 = 0, r_c2 = 0, cw21=None, cw22=None):

        """assigining the frist specific duty cycle for the appliace (maximum of three cycles can be assigned)

        Parameters
        ----------
        p_21 : float, optional
            Power rating for first part of second duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_21 : int[0,1440], optional
            Duration (minutes) of first part of second duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        p_22 : int, float, optional
            Power rating for second part of second duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_22 : int[0,1440], optional
            Duration (minutes) of second part of second duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        r_c2 : Percentage [0,1], optional
            randomization of the duty cycle parts duration. There will be a uniform random variation around t_i1 and t_i2. If this parameter is set to 0.1, then t_i1 and t_i2 will be randomly reassigned between 90% and 110% of their initial value; 0 means no randomisation, by default 0

        cw21 : Iterable, optional
            Window time range for the first part of second duty cycle number (not neccessarily linked to the overall time window), by default None

        cw22 : Iterable, optional
            Window time range for the first part of second duty cycle number (not neccessarily linked to the overall time window), by default None, by default None
        """
        self.p_21 = p_21
        self.t_21 = int(t_21)
        self.p_22 = p_22
        self.t_22 = int(t_22)
        self.r_c2 = r_c2
        if cw21 is not None:
            self.cw21 = cw21
        if cw22 is not None:
            self.cw22 = cw22
        # Below is not used
        self.fixed_cycle2 = np.concatenate(((np.ones(self.t_21)*p_21),(np.ones(self.t_22)*p_22)))

    def specific_cycle_3(self, p_31 = 0, t_31 = 0, p_32 = 0, t_32 = 0, r_c3 = 0, cw31=None, cw32=None):
        """assigining the frist specific duty cycle for the appliace (maximum of three cycles can be assigned)

        Parameters
        ----------
        p_21 : float, optional
            Power rating for first part of third duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_21 : int[0,1440], optional
            Duration (minutes) of first part of third duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        p_22 : int, float, optional
            Power rating for second part of third duty cycle. Only necessary if fixed_cycle is set to 1 or greater, by default 0

        t_22 : int[0,1440], optional
            Duration (minutes) of second part of third duty cycle. Only necessary if fixed_cycle is set to I or greater, by default 0

        r_c2 : Percentage [0,1], optional
            randomization of the duty cycle parts duration. There will be a uniform random variation around t_i1 and t_i2. If this parameter is set to 0.1, then t_i1 and t_i2 will be randomly reassigned between 90% and 110% of their initial value; 0 means no randomisation, by default 0

        cw21 : Iterable, optional
            Window time range for the first part of third duty cycle number (not neccessarily linked to the overall time window), by default None

        cw22 : Iterable, optional
            Window time range for the first part of third duty cycle number (not neccessarily linked to the overall time window), by default None, by default None
        """
        self.p_31 = p_31
        self.t_31 = int(t_31)
        self.p_32 = p_32
        self.t_32 = int(t_32)
        self.r_c3 = r_c3
        if cw31 is not None:
            self.cw31 = cw31
        if cw32 is not None:
            self.cw32 = cw32
        # Below is not used
        self.fixed_cycle3 = np.concatenate(((np.ones(self.t_31)*p_31),(np.ones(self.t_32)*p_32)))

    #different time windows can be associated with different specific duty cycles
    def cycle_behaviour(self, cw11 = np.array([0,0]), cw12 = np.array([0,0]), cw21 = np.array([0,0]), cw22 = np.array([0,0]), cw31 = np.array([0,0]), cw32 = np.array([0,0])):
        """_summary_

        Parameters
        ----------
        cw11 : Iterable, optional
            Window time range for the first part of first duty cycle number, by default np.array([0,0])
        cw12 : Iterable, optional
            Window time range for the second part of first duty cycle number, by default np.array([0,0])
        cw21 : Iterable, optional
            Window time range for the first part of second duty cycle number, by default np.array([0,0])
        cw22 : Iterable, optional
            Window time range for the second part of second duty cycle number, by default np.array([0,0])
        cw31 : Iterable, optional
            Window time range for the first part of third duty cycle number, by default np.array([0,0])
        cw32 : Iterable, optional
            Window time range for the second part of third duty cycle number, by default np.array([0,0])
        """
        # only used around line 223
        self.cw11 = cw11 #first window associated with cycle1
        self.cw12 = cw12 #second window associated with cycle1
        self.cw21 = cw21 #same for cycle2
        self.cw22 = cw22
        self.cw31 = cw31 #same for cycle 3
        self.cw32 = cw32

    def rand_total_time_of_use(
        self,
        rand_window_1: Iterable[int],
        rand_window_2: Iterable[int],
        rand_window_3: Iterable[int],
        ) -> int:
        """Randomised total time of use of the Appliance instance
        """

        random_var_t = random_variation(var=self.time_fraction_random_variability)

        rand_time = round(
            random.uniform(self.func_time, int(self.func_time * random_var_t))
        )

        if rand_time < self.func_cycle:
            rand_time = self.func_cycle

        # total time available for appliance usage
        total_time = (
            (rand_window_1[1] - rand_window_1[0])
            + (rand_window_2[1] - rand_window_2[0])
            + (rand_window_3[1] - rand_window_3[0])
        )

        # check that the total randomised time of use does not exceed the total time available
        if rand_time > 0.99 * total_time:
            rand_time = int(0.99 * total_time)

        if rand_time < self.func_cycle:
            raise ValueError(f"The func_cycle you choose for appliance {self.name} might be too large to fit in the available time for appliance usage, please either reduce func_cycle or increase the windows of use of the appliance")
        return rand_time

    def rand_switch_on_window(self, rand_time:int):
        """Identifies a random switch on window within the available functioning windows

        This corresponds to step 2c. of:

            F. Lombardi, S. Balderrama, S. Quoilin, E. Colombo,
            Generating high-resolution multi-energy load profiles for remote areas with an open-source stochastic model,
            Energy, 2019, https://doi.org/10.1016/j.energy.2019.04.097.
        """

        indexes_choice = []
        for s in self.free_spots:
            if s.stop - s.start >= self.func_cycle:
                indexes_choice += [*range(s.start, s.stop - self.func_cycle + 1)] # this will be fast with cython
        n_choices = len(indexes_choice)
        if n_choices > 0:
            # Identifies a random switch on time within the available functioning windows
            # step 2c of [1]
            switch_on = indexes_choice[random.randint(0, n_choices-1)]
            spot_idx = None
            for i, fs in enumerate(self.free_spots):
                if fs.start <= switch_on <= fs.stop - self.func_cycle:
                    spot_idx = i
                    break

            largest_duration = min(rand_time, self.free_spots[spot_idx].stop - switch_on)

            if largest_duration > self.func_cycle:
                indexes = np.arange(switch_on, switch_on + (
                    int(random.uniform(self.func_cycle, largest_duration))))  # TODO randint
            elif largest_duration == self.func_cycle:
                indexes = np.arange(switch_on, switch_on + largest_duration)
            else:
                print("func time", self.func_cycle)
                print("max window", self.free_spots[spot_idx].stop)
                print("rand_time", rand_time)
                print("upper_limit", largest_duration)
                raise ValueError("There is something fishy with upper limit in switch on...")
        else:
            indexes = None
            # there are no available windows anymore

        return indexes

    def calc_coincident_switch_on(self, inside_peak_window:bool=True):
        """Computes how many of the 'n' Appliance instance are switched on simultaneously

        Implement eqs. 3 and 4 of [1]

        [1] F. Lombardi, S. Balderrama, S. Quoilin, E. Colombo,
            Generating high-resolution multi-energy load profiles for remote areas with an open-source stochastic model,
            Energy, 2019, https://doi.org/10.1016/j.energy.2019.04.097.
        """
        s_peak, mu_peak, op_factor = switch_on_parameters()

        # check if indexes are within peak window
        if inside_peak_window is True and self.fixed == 'no':
            # calculates coincident behaviour within the peak time range
            # eq. 4 of [1]
            coincidence = min(self.number, max(1, math.ceil(random.gauss(mu=(self.number * mu_peak + 0.5), sigma=(s_peak * self.number * mu_peak)))))
        # check if indexes are off-peak
        elif inside_peak_window is False and self.fixed == 'no':
            # calculates probability of coincident switch_ons off-peak
            # eq. 3 of [1]
            prob = random.uniform(0, (self.number - op_factor) / self.number)

            # randomly selects how many appliances are on at the same time
            array = np.arange(0, self.number) / self.number
            try:
                on_number = np.max(np.where(prob >= array)) + 1
            except ValueError:
                on_number = 1

            coincidence = on_number
        else:
            # All 'n' copies of an Appliance instance are switched on altogether
            coincidence = self.number
        return coincidence

    def generate_load_profile(self, prof_i, peak_time_range, day_type, power):
        """Generate load profile of the Appliance instance by updating its daily_use attribute

        Run steps 2a and 2b and repeat steps 2c – 2e of [1] until the sum of the durations of
        all the switch-on events equals the randomised total time of use of the Appliance

        [1] F. Lombardi, S. Balderrama, S. Quoilin, E. Colombo,
            Generating high-resolution multi-energy load profiles for remote areas with an open-source stochastic model,
            Energy, 2019, https://doi.org/10.1016/j.energy.2019.04.097.
        """
        # initialises variables for the cycle
        self.daily_use = np.zeros(1440)

        rand_daily_pref = 0 if self.user.user_preference == 0 else random.randint(1, self.user.user_preference)

        # skip this appliance in any of the following applies
        if (
                # evaluates if occasional use happens or not
                (random.uniform(0, 1) > self.occasional_use
                 # evaluates if daily preference coincides with the randomised daily preference number
                 or (self.pref_index != 0 and rand_daily_pref != self.pref_index)
                 # checks if the app is allowed in the given yearly behaviour pattern
                 or self.wd_we_type not in [day_type, 2])
        ):
            return

        # recalculate windows start and ending times randomly, based on the inputs
        rand_window_1 = self.calc_rand_window(window_idx=1)
        rand_window_2 = self.calc_rand_window(window_idx=2)
        rand_window_3 = self.calc_rand_window(window_idx=3)
        rand_windows = [rand_window_1, rand_window_2, rand_window_3]

        # random variability is applied to the total functioning time and to the duration
        # of the duty cycles provided they have been specified
        # step 2a of [1]
        rand_time = self.rand_total_time_of_use(rand_window_1, rand_window_2, rand_window_3)

        # redefines functioning windows based on the previous randomisation of the boundaries
        # step 2b of [1]
        if self.flat == 'yes':
            # for "flat" appliances the algorithm stops right after filling the newly
            # created windows without applying any further stochasticity
            total_power_value = self.power[prof_i] * self.number
            for rand_window in rand_windows:
                self.daily_use[rand_window[0]:rand_window[1]] = np.full(np.diff(rand_window),
                                                                       total_power_value)
            #single_load = single_load + self.daily_use
            return
        else:
            # "non-flat" appliances a mask is applied on the newly defined windows and
            # the algorithm goes further on
            for rand_window in rand_windows:
                self.daily_use[rand_window[0]:rand_window[1]] = np.full(np.diff(rand_window), 0.001)

        # calculates randomised cycles taking the random variability in the duty cycle duration
        self.assign_random_cycles()

        # steps 2c-2e repeated until the sum of the durations of all the switch-on events equals rand_time



        self.free_spots = [slice(rw[0], rw[1], None) for rw in rand_windows if rw[0] != rw[1]]

        tot_time = 0
        while tot_time <= rand_time:



            # one option could be to generate a lot of them at once
            indexes = self.rand_switch_on_window(
                rand_time=rand_time, #TODO maybe only consider rand_time-tot_time ...
            )
            if indexes is None:
                break # exit cycle and go to next Appliance as there are no available windows anymore


            # the count of total time is updated with the size of the indexes array
            tot_time = tot_time + indexes.size

            if tot_time > rand_time:
                # the total functioning time is reached, a correction is applied to avoid overflow of indexes
                indexes_adj = indexes[:-(tot_time - rand_time)]
                if len(indexes_adj) > 0:
                    inside_peak_window = within_peak_time_window(indexes_adj[0], indexes_adj[-1], peak_time_range[0], peak_time_range[-1])

                    # Computes how many of the 'n' of the Appliance instance are switched on simultaneously
                    coincidence = self.calc_coincident_switch_on(
                        inside_peak_window
                    )
                    # Update the daily use depending on existence of duty cycles of the Appliance instance
                    self.update_daily_use(
                        coincidence,
                        power=power,
                        indexes=indexes_adj
                    )
                break  # exit cycle and go to next Appliance

            else:
                inside_peak_window = within_peak_time_window(indexes[0], indexes[-1], peak_time_range[0], peak_time_range[-1])



                coincidence = self.calc_coincident_switch_on(
                    inside_peak_window
                )
                # Update the daily use depending on existence of duty cycles of the Appliance instance
                self.update_daily_use(
                    coincidence,
                    power=power,
                    indexes=indexes
                )



