"""
photovoltaic
"""


from __future__ import division
import numpy as np
import pandas as pd
import math
from math import *
from cea.utilities import dbfreader
from scipy import interpolate

from cea.utilities import epwreader
from cea.utilities import solar_equations
import time

__author__ = "Jimeno A. Fonseca"
__copyright__ = "Copyright 2016, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Jimeno A. Fonseca, Shanshan Hsieh"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "cea@arch.ethz.ch"
__status__ = "Production"


# PV electricity generation

def calc_PV(locator, radiation_csv, metadata_csv, latitude, longitude, gv, weather_path, building_name):
    """
    This function first determines the surface area with sufficient solar radiation, and then calculates the optimal
    tilt angles of panels at each surface location. The panels are categorized into groups by their surface azimuths,
    tilt angles, and global irradiation. In the last, electricity generation from PV panels of each group is calculated.

    :param locator: An InputLocator to locate input files
    :type locator: cea.inputlocator.InputLocator
    :param gv: global variables
    :type gv: cea.globalvar.GlobalVariables
    :param radiation_csv: solar insulation data on all surfaces of each building
    :type radiation_csv: .csv
    :param metadata_csv: data of sensor points measuring solar insulation of each building
    :type metadata_csv: .csv
    :param latitude: latitude of the case study location
    :type latitude: float
    :param longitude: longitude of the case study location
    :type longitude: float
    :param weather_path: path to the weather data file of the case study location
    :type weather_path: .epw
    :param building_name: list of building names in the case study
    :type building_name: Series
    :return: Building_PV.csv with PV generation potential of each building, Building_sensors.csv with sensor data of
    each PV panel.
    """
    t0 = time.clock()

    # weather data
    weather_data = epwreader.epw_reader(weather_path)
    gv.log('reading weather data done')

    # solar properties
    g, Sz, Az, ha, trr_mean, worst_sh, worst_Az = solar_equations.calc_sun_properties(latitude, longitude, weather_data,
                                                                         gv)
    gv.log('calculating solar properties done')

    # select sensor point with sufficient solar radiation
    max_yearly_radiation, min_yearly_production, sensors_rad_clean, sensors_metadata_clean = \
        filter_low_potential(weather_data, radiation_csv, metadata_csv, gv)

    gv.log('filtering low potential sensor points done')

    if not sensors_metadata_clean.empty:
        # calculate optimal angle and tilt for panels
        sensors_metadata_cat = optimal_angle_and_tilt(sensors_metadata_clean, latitude, worst_sh, worst_Az, trr_mean,
                                                      gv.module_length_PV, max_yearly_radiation)
        gv.log('calculating optimal tile angle and separation done')

        # group the sensors with the same tilt, surface azimuth, and total radiation
        Number_groups, hourlydata_groups, number_points, prop_observers = calc_groups(sensors_rad_clean, sensors_metadata_cat)

        gv.log('generating groups of sensor points done')

        results, Final = calc_pv_generation(gv.type_PVpanel, hourlydata_groups, Number_groups, number_points,
                                        prop_observers, weather_data, g, Sz, Az, ha, latitude, gv.misc_losses)


        Final.to_csv(locator.PV_results(building_name= building_name), index=True, float_format='%.2f')  # print PV generation potential
        sensors_metadata_cat.to_csv(locator.metadata_results(building_name= building_name), index=True, float_format='%.2f')  # print selected metadata of the selected sensors
        gv.log('done - time elapsed: %(time_elapsed).2f seconds', time_elapsed=time.clock() - t0)
    return

def filter_low_potential(weather_data, radiation_csv, metadata_csv, gv):
    """
    To filter the sensor points/hours with low radiation potential.

    :param weather_data: weather data read from the epw file
    :type weather_data: dataframe
    :param radiation_csv: solar insulation data on all surfaces of each building
    :type radiation_csv: .csv
    :param metadata_csv: solar insulation sensor data of each building
    :type metadata_csv: .csv
    :param gv: global variables
    :type gv: cea.globalvar.GlobalVariables
    :return max_yearly_radiation: yearly horizontal radiation [Wh/m2/year]
    :rtype max_yearly_radiation: float
    :return min_yearly_radiation: minimum yearly radiation threshold for sensor selection [Wh/m2/year]
    :rtype min_yearly_radiation: float
    :return sensors_rad_clean: radiation data of the filtered sensors [Wh/m2]
    :rtype sensors_rad_clean: dataframe
    :return sensors_metadata_clean: data of filtered sensor points measuring solar insulation of each building
    :rtype sensors_metadata_clean: dataframe

    Assumptions
    -----------
    1) Sensor points with low yearly radiation are deleted. The threshold (minimum yearly radiation) is a percentage
    of global horizontal radiation. The percentage threshold (min_radiation) is a global variable defined by users.
    2) For each sensor point kept, the radiation value is set to zero when radiation value is below 50 W/m2.
    3) No solar panels on windows.
    """
    # get max radiation potential from global horizontal radiation
    yearly_horizontal_rad = weather_data.glohorrad_Whm2.sum()  # [Wh/m2/year]

    # read radiation file
    sensors_rad = pd.read_csv(radiation_csv)
    sensors_metadata = pd.read_csv(metadata_csv)

    # join total radiation to sensor_metadata
    sensors_rad_sum = sensors_rad.sum(0).values # add new row with yearly radiation
    sensors_metadata['total_rad_Whm2'] = sensors_rad_sum    #[Wh/m2]

    # remove window surfaces
    sensors_metadata = sensors_metadata[sensors_metadata.TYPE != 'window']

    # keep sensors if allow pv installation on walls or on roofs
    if gv.pvonroof is False:
        sensors_metadata = sensors_metadata[sensors_metadata.TYPE != 'roof']
    if gv.pvonwall is False:
        sensors_metadata = sensors_metadata[sensors_metadata.TYPE != 'wall']

    # keep sensors above min production in sensors_rad
    sensors_metadata = sensors_metadata.set_index('SURFACE')
    max_yearly_radiation = yearly_horizontal_rad
    # set min yearly radiation threshold for sensor selection
    min_yearly_radiation = max_yearly_radiation * gv.min_radiation

    sensors_metadata_clean = sensors_metadata[sensors_metadata.total_rad_Whm2 >= min_yearly_radiation]
    sensors_rad_clean = sensors_rad[sensors_metadata_clean.index.tolist()] # keep sensors above min radiation

    sensors_rad_clean[sensors_rad_clean[:] <= 50] = 0   # eliminate points when hourly production < 50 W/m2

    return max_yearly_radiation, min_yearly_radiation, sensors_rad_clean, sensors_metadata_clean

  
def calc_pv_generation(type_panel, hourly_radiation, number_groups, number_points, prop_observers, weather_data,
                       g, Sz, Az, ha, latitude, misc_losses):
    """
    To calculate the electricity generated from PV panels.
    :param type_panel: type of PV panel used
    :type type_panel: float
    :param hourly_radiation: mean hourly radiation of sensors in each group [Wh/m2]
    :type hourly_radiation: dataframe
    :param number_groups: number of groups of sensor points
    :type number_groups: float
    :param number_points: number of sensor points in each group
    :type number_points: float
    :param prop_observers: mean values of sensor properties of each group of sensors
    :type prop_observers: dataframe
    :param weather_data: weather data read from the epw file
    :type weather_data: dataframe
    :param g: declination
    :type g: float
    :param Sz: zenith angle
    :type Sz: float
    :param Az: solar azimuth

    :param ha: hour angle
    :param latitude: latitude of the case study location
    :param misc_losses: expected system loss [-]
    :return:
    """

    # convert degree to radians
    lat = radians(latitude)
    g_vector = np.radians(g)
    ha_vector = np.radians(ha)
    Sz_vector = np.radians(Sz)
    Az_vector = np.radians(Az)

    result = list(range(number_groups))
    groups_area = list(range(number_groups))
    Sum_PV = np.zeros(8760)

    n = 1.526 # refractive index of glass
    Pg = 0.2  # ground reflectance
    K = 0.4   # extinction coefficient
    eff_nom,NOCT,Bref,a0,a1,a2,a3,a4,L = calc_properties_PV(type_panel)

    for group in range(number_groups):
        # read panel properties of each group
        teta_z = prop_observers.loc[group,'surface_azimuth']
        area_per_group = prop_observers.loc[group,'total_area_pv']
        tilt_angle = prop_observers.loc[group,'B']
        # degree to radians
        tilt = radians(tilt_angle) #tilt angle
        teta_z = radians(teta_z) #surface azimuth

        # read radiation data of each group
        radiation = pd.DataFrame({'I_sol':hourly_radiation[group]})
        radiation['I_diffuse'] = weather_data.ratio_diffhout.fillna(0)*radiation.I_sol  #calculate diffuse radiation
        radiation['I_direct'] = radiation['I_sol'] - radiation['I_diffuse']   #calculat direct radaition

        #calculate effective indicent angles necessary
        teta_vector = np.vectorize(calc_angle_of_incidence)(g_vector, lat, ha_vector, tilt, teta_z)
        teta_ed, teta_eg  = calc_diffuseground_comp(tilt)

        results = np.vectorize(Calc_Sm_PV)(weather_data.drybulb_C, radiation.I_sol, radiation.I_direct,
                                           radiation.I_diffuse, tilt, Sz_vector, teta_vector, teta_ed, teta_eg, n, Pg,
                                           K, NOCT, a0, a1, a2, a3, a4, L)
        result[group] = np.vectorize(Calc_PV_power)(results[0], results[1], eff_nom, area_per_group, Bref, misc_losses)
        groups_area[group] = area_per_group

        Sum_PV = Sum_PV + result[group] # in kWh
    total_area = sum(groups_area)
    Final = pd.DataFrame({'PV_kWh':Sum_PV,'Area':total_area})
    return result, Final

def calc_incidenteangleB(g, lat, ha, tilt, teta_z):
    """
    Calculates the angle of incidence (angle between the solar vector and the surface normal)
    :param g: declination
    :param lat: latitude of the case study location
    :param ha: hour angle
    :param tilt: panel tilt angle [rad]
    :param teta_z: panel surface azimuth [rad]
    :return teta_B: incident angle [rad]
    """

    # calculate incident angle beam radiation
    part1 = sin(lat) * sin(g) * cos(tilt) - cos(lat) * sin(g) * sin(tilt) * cos(teta_z)
    part2 = cos(lat) * cos(g) * cos(ha) * cos(tilt) + sin(lat) * cos(g) * cos(ha) * sin(tilt) * cos(teta_z)
    part3 = cos(g) * sin(ha) * sin(tilt) * sin(teta_z)
    teta_B = acos(part1 + part2 + part3)
    return teta_B  # in radains

def calc_angle_of_incidence(g, lat, ha, tilt, teta_z):
    """
    To calculate angle of incidence from solar vector and surface normal vector.

    :param lat: latitude of the loacation of case study [radians]
    :param g: declination of the solar position [radians]
    :param ha: hour angle [radians]
    :param tilt: panel surface tilt angle [radians]
    :param teta_z: panel surface azimuth angle [radians]
    :type lat: float
    :type g: float
    :type ha: float
    :type tilt: float
    :type teta_z: float
    :return teta_B: angle of incidence [radians]
    :rtype teta_B: float
    """
    # surface normal vector
    n_E = sin(tilt)*sin(teta_z)
    n_N = sin(tilt)*cos(teta_z)
    n_Z = cos(tilt)
    # solar vector
    s_E = -cos(g)*sin(ha)
    s_N = sin(g)*cos(lat) - cos(g)*sin(lat)*cos(ha)
    s_Z = cos(g)*cos(lat)*cos(ha) + sin(g)*sin(lat)

    # angle of incidence
    teta_B = acos(n_E*s_E + n_N*s_N + n_Z*s_Z)
    return teta_B

def calc_diffuseground_comp(tilt_radians):
    """
    To calculate reflected radiation and diffuse radiation.

    :param tilt_radians:  surface tilt angle [radians]
    :type tilt_radians: float
    :return teta_ed: groups-reflected radiation
    :return teta_eg: diffuse radiation
    :rtype teta_ed: float
    :rtype teta_eg: float

    References
    ----------
    Duffie, J. A. and Beckman, W. A. (2013) Radiation Transmission through Glazing: Absorbed Radiation, in
    Solar Engineering of Thermal Processes, Fourth Edition, John Wiley & Sons, Inc., Hoboken, NJ, USA.
    doi: 10.1002/9781118671603.ch5
    """
    tilt = degrees(tilt_radians)
    teta_ed = 59.68 - 0.1388 * tilt + 0.001497 * tilt ** 2  # angle in degrees
    teta_eG = 90 - 0.5788 * tilt + 0.002693 * tilt ** 2  # angle in degrees
    return radians(teta_ed), radians(teta_eG)

def Calc_Sm_PV(te, I_sol, I_direct, I_diffuse, tilt, Sz, teta, tetaed, tetaeg,
               n, Pg, K, NOCT, a0, a1, a2, a3, a4, L):
    """
    To calculate the absorbed solar radiation on tilted surface.

    :param te:
    :param I_sol:
    :param I_direct:
    :param I_diffuse:
    :param tilt:
    :param Sz:
    :param teta:
    :param tetaed:
    :param tetaeg:
    :param n:
    :param Pg:
    :param K:
    :param NOCT:
    :param a0:
    :param a1:
    :param a2:
    :param a3:
    :param a4:
    :param L:
    :return:

    References
    ----------
    Duffie, J. A. and Beckman, W. A. (2013) Radiation Transmission through Glazing: Absorbed Radiation, in
    Solar Engineering of Thermal Processes, Fourth Edition, John Wiley & Sons, Inc., Hoboken, NJ, USA.
    doi: 10.1002/9781118671603.ch5
    """

    # calcualte ratio of beam radiation on a tilted plane
    # to avoid inconvergence when I_sol = 0
    lim1 = radians(0)
    lim2 = radians(90)
    lim3 = radians(89.999)

    if teta < lim1:
        teta = min(lim3, abs(teta))
    if teta >= lim2:
        teta = lim3

    if Sz < lim1:
        Sz = min(lim3, abs(Sz))
    if Sz >= lim2:
        Sz = lim3
    # Rb: ratio of beam radiation of tilted surface to that on horizontal surface
    Rb = cos(teta) / cos(Sz)  # Sz is Zenith angle

    # calculate the specific air mass, m
    m = 1 / cos(Sz)
    M = a0 + a1 * m + a2 * m ** 2 + a3 * m ** 3 + a4 * m ** 4

    # angle refractive  (aproximation accrding to Soteris A.)
    teta_r = asin(sin(teta) / n)  # in radians
    Ta_n = exp(-K * L) * (1 - ((n - 1) / (n + 1)) ** 2)
    # calculate parameters of anlge modifier #first for the direct radiation
    if teta < 1.5707:  # 90 degrees in radians
        part1 = teta_r + teta
        part2 = teta_r - teta
        Ta_B = exp((-K * L) / cos(teta_r)) * (
        1 - 0.5 * ((sin(part2) ** 2) / (sin(part1) ** 2) + (tan(part2) ** 2) / (tan(part1) ** 2)))
        kteta_B = Ta_B / Ta_n
    else:
        kteta_B = 0

    # angle refractive for diffuse radiation
    teta_r = asin(sin(tetaed) / n)  # in radians
    part1 = teta_r + tetaed
    part2 = teta_r - tetaed
    Ta_D = exp((-K * L) / cos(teta_r)) * (
    1 - 0.5 * ((sin(part2) ** 2) / (sin(part1) ** 2) + (tan(part2) ** 2) / (tan(part1) ** 2)))
    kteta_D = Ta_D / Ta_n

    # angle refractive for global radiatoon
    teta_r = asin(sin(tetaeg) / n)  # in radians
    part1 = teta_r + tetaeg
    part2 = teta_r - tetaeg
    Ta_eG = exp((-K * L) / cos(teta_r)) * (
    1 - 0.5 * ((sin(part2) ** 2) / (sin(part1) ** 2) + (tan(part2) ** 2) / (tan(part1) ** 2)))
    kteta_eG = Ta_eG / Ta_n

    # absorbed solar radiation
    S = M * Ta_n * (kteta_B * I_direct * Rb + kteta_D * I_diffuse * (1 + cos(tilt)) / 2 + kteta_eG * I_sol * Pg * (
    1 - cos(tilt)) / 2)  # in W/m2
    if S <= 0:  # when points are 0 and too much losses
        S = 0
    # temperature of cell
    Tcell = te + S * (NOCT - 20) / (800)   # assuming linear temperature rise vs radiation according to NOCT condition

    return S, Tcell

def Calc_PV_power(S, Tcell, eff_nom, areagroup, Bref, misc_losses):
    """
    To calculate the power production of PV panels.

    :param S: absorbed radiation [W/m2]
    :type S: float
    :param Tcell: cell temperature [degree]
    :param eff_nom: nominal efficiency of PV module [-]
    :type eff_nom: float
    :param areagroup: PV module area [m2]
    :type areagroup: float
    :param Bref: cell maximum power temperature coefficient [degree C^(-1)]
    :type Bref: float
    :param misc_losses: expected system loss [-]
    :type misc_losses: float
    :return P: Power production [kW]
    :rtype P: float

    ..[Osterwald, C. R., 1986] Osterwald, C. R. (1986). Translation of device performance measurements to
    reference conditions. Solar Cells, 18, 269-279.
    """
    P = eff_nom*areagroup*S*(1-Bref*(Tcell-25))*(1-misc_losses)/1000
    return P


"""
============================
optimal angle and tilt
============================

"""


def calc_optimal_angle(teta_z, latitude, transmissivity):
    """
    To calculate the optimal tilt angle of the solar panels.

    :param teta_z: surface azimuth, 0 degree south (east negative) or 0 degree north (east positive)
    :type teta_z: float
    :param latitude: latitude of the case study site
    :type latitude: float
    :param transmissivity: clearness index [-]
    :type transmissivity: float
    :return abs(b): optimal tilt angle [radians]
    :rtype abs(b): float

    ..[Quinn et al., 2013] S.W.Quinn, B.Lehman.A simple formula for estimating the optimum tilt angles of photovoltaic
    panels. 2013 IEEE 14th Work Control Model Electron, Jun, 2013, pp.1-8
    """
    if transmissivity <= 0.15:
        gKt = 0.977
    elif 0.15 < transmissivity <= 0.7:
        gKt = 1.237 - 1.361 * transmissivity
    else:
        gKt = 0.273
    Tad = 0.98  # transmittance-absorptance product of the diffuse radiation
    Tar = 0.97  # transmittance-absorptance product of the reflected radiation
    Pg = 0.2    # ground reflectance of 0.2
    l = radians(latitude)
    a = radians(teta_z)
    b = atan((cos(a) * tan(l)) * (1 / (1 + ((Tad * gKt - Tar * Pg) / (2 * (1 - gKt))))))  # eq.(11)
    return abs(b)


def Calc_optimal_spacing(Sh, Az, tilt_angle, module_length):
    """
    To calculate the optimal spacing between each panel to avoid shading.

    :param Sh: Solar elevation at the worst hour [degree]
    :type Sh: float
    :param Az: Solar Azimuth [degree]
    :type Az: float
    :param tilt_angle: optimal tilt angle for panels on flat surfaces [degree]
    :type tilt_angle: float
    :param module_length: [m]
    :type module_length: float
    :return D: optimal distance in [m]
    :rtype D: float
    """
    h = module_length * sin(tilt_angle)
    D1 = h / tan(radians(Sh))
    D = max(D1 * cos(radians(180 - Az)), D1 * cos(radians(Az - 180)))
    return D


def calc_categoriesroof(teta_z, B, GB, Max_Isol):
    """
    To categorize solar panels by the surface azimuth, tilt angle and yearly radiation.

    :param teta_z: surface azimuth [degree], 0 degree north (east positive, west negative)
    :type teta_z: float
    :param B: solar panel tile angle [degree]
    :type B: float
    :param GB: yearly radiation of sensors [Wh/m2/year]
    :type GB: float
    :param Max_Isol: yearly global horizontal radiation [Wh/m2/year]
    :type Max_Isol: float
    :return CATteta_z: category of surface azimuth
    :rtype CATteta_z: float
    :return CATB: category of tilt angle
    :rtype CATB: float
    :return CATBG: category of yearly radiation
    :rtype CATBG: float
    """
    if -122.5 < teta_z <= -67:
        CATteta_z = 1
    elif -67 < teta_z <= -22.5:
        CATteta_z = 3
    elif -22.5 < teta_z <= 22.5:
        CATteta_z = 5
    elif 22.5 < teta_z <= 67:
        CATteta_z = 4
    elif 67 <= teta_z <= 122.5:
        CATteta_z = 2
    else:
        CATteta_z = 6
    B = degrees(B)
    if 0 < B <= 5:
        CATB = 1  # flat roof
    elif 5 < B <= 15:
        CATB = 2  # tilted 5-15 degrees
    elif 15 < B <= 25:
        CATB = 3  # tilted 15-25 degrees
    elif 25 < B <= 40:
        CATB = 4  # tilted 25-40 degrees
    elif 40 < B <= 60:
        CATB = 5  # tilted 40-60 degrees
    elif B > 60:
        CATB = 6  # tilted >60 degrees
    else:
        CATB = None
        print('B not in expected range')

    GB_percent = GB / Max_Isol
    if 0 < GB_percent <= 0.25:
        CATGB = 1
    elif 0.25 < GB_percent <= 0.50:
        CATGB = 2
    elif 0.50 < GB_percent <= 0.75:
        CATGB = 3
    elif 0.75 < GB_percent <= 0.90:
        CATGB = 4
    elif 0.90 < GB_percent:
        CATGB = 5
    else:
        CATGB = None
        print('GB not in expected range')

    return CATteta_z, CATB, CATGB

def optimal_angle_and_tilt(sensors_metadata_clean, latitude, worst_sh, worst_Az, transmissivity,
                           module_length, Max_Isol):
    """
    This function first determines the optimal tilt angle, row spacing and surface azimuth of panels installed at each
    sensor point. Secondly, the installed PV module areas at each sensor point are calculated. Lastly, all the modules
    are categorized with its surface azimuth, tilt angle, and yearly radiation. The output will then be used to
    calculate the absorbed radiation.

    :param sensors_metadata_clean: data of filtered sensor points measuring solar insulation of each building
    :type sensors_metadata_clean: dataframe
    :param latitude: latitude of the case study location
    :type latitude: float
    :param worst_sh: solar elevation at the worst hour [degree]
    :type worst_sh: float
    :param worst_Az: solar azimuth at the worst hour [degree]
    :type worst_Az: float
    :param transmissivity: transmissivity: clearness index [-]
    :type transmissivity: float
    :param module_length: length of the PV module [m]
    :type module_length: float
    :param Max_Isol: max radiation potential (equals to global horizontal radiation) [Wh/m2/year]
    :type Max_Isol: float

    :returns sensors_metadata_clean: data of filtered sensor points categorized with module tilt angle, array spacing,
    surface azimuth, installed PV module area of each sensor point and the categories
    :rtype sensors_metadata_clean: dataframe

    Assumptions
    -----------
    1) Tilt angle: If the sensor is on tilted roof, the panel will have the same tilt as the roof. If the sensor is on
       a wall, the tilt angle is 90 degree. Tilt angles for flat roof is determined using the method from Quinn et al.
    2) Row spacing: Determine the row spacing by minimizing the shadow according to the solar elevation and azimuth at
       the worst hour of the year. The worst hour is a global variable defined by users.
    3) Surface azimuth (orientation) of panels: If the sensor is on a tilted roof, the orientation of the panel is the
        same as the roof. Sensors on flat roofs are all south facing.
    """
    # calculate panel tilt angle (B) for flat roofs (tilt < 5 degrees), slope roofs and walls.
    optimal_angle_flat = calc_optimal_angle(180, latitude, transmissivity) # assume surface azimuth = 180 (N,E), south facing
    sensors_metadata_clean['tilt']= np.vectorize(math.acos)(sensors_metadata_clean['Zdir']) #surface tilt angle in rad
    sensors_metadata_clean['tilt'] = np.vectorize(math.degrees)(sensors_metadata_clean['tilt']) #surface tilt angle in degrees
    sensors_metadata_clean['B'] = np.where(sensors_metadata_clean['tilt'] >= 5, sensors_metadata_clean['tilt'],
                                           degrees(optimal_angle_flat)) # panel tilt angle in degrees

    # calculate spacing and surface azimuth of the panels for flat roofs
    optimal_spacing_flat = Calc_optimal_spacing(worst_sh, worst_Az, optimal_angle_flat, module_length)
    sensors_metadata_clean['array_s'] = np.where(sensors_metadata_clean['tilt'] >= 5, 0, optimal_spacing_flat)
    sensors_metadata_clean['surface_azimuth'] = np.vectorize(calc_surface_azimuth)(sensors_metadata_clean['Xdir'],
                                                                                   sensors_metadata_clean['Ydir'],
                                                                                   sensors_metadata_clean['B'])  # degrees

    # calculate the surface area required to install one pv panel on flat roofs with defined tilt angle and array spacing
    surface_area_flat = module_length * (
    sensors_metadata_clean.array_s / 2 + module_length * [cos(optimal_angle_flat)])

    # calculate the pv module area within the area of each sensor point
    sensors_metadata_clean['area_netpv'] = np.where(sensors_metadata_clean['tilt'] >= 5, sensors_metadata_clean.AREA_m2,
                                                    module_length**2 * (sensors_metadata_clean.AREA_m2/surface_area_flat))

    # categorize the sensors by surface_azimuth, B, GB
    result = np.vectorize(calc_categoriesroof)(sensors_metadata_clean.surface_azimuth, sensors_metadata_clean.B,
                                               sensors_metadata_clean.total_rad_Whm2, Max_Isol)
    sensors_metadata_clean['CATteta_z'] = result[0]
    sensors_metadata_clean['CATB'] = result[1]
    sensors_metadata_clean['CATGB'] = result[2]
    return sensors_metadata_clean

def calc_surface_azimuth(xdir, ydir, B):
    """
    Calculate surface azimuth from the surface normal vector (x,y,z) and tilt angle (B).
    Following the geological sign convention, an azimuth of 0 and 360 degree represents north, 90 degree is east.

    :param xdir: surface normal vector x in (x,y,z) representing east-west direction
    :param ydir: surface normal vector y in (x,y,z) representing north-south direction
    :param B: surface tilt angle in degree
    :type xdir: float
    :type ydir: float
    :type B: float
    :returns surface azimuth: the azimuth of the surface of a solar panel in degree
    :rtype surface_azimuth: float

    """
    B = math.radians(B)
    teta_z = math.degrees(math.asin(xdir / math.sin(B)))
    # set the surface azimuth with on the sing convention (E,N)=(+,+)
    if xdir < 0:
        if ydir <0:
            surface_azimuth = 180 + teta_z     # (xdir,ydir) = (-,-)
        else: surface_azimuth = 360 + teta_z   # (xdir,ydir) = (-,+)
    elif ydir < 0:
        surface_azimuth = 180 + teta_z         # (xdir,ydir) = (+,-)
    else: surface_azimuth = teta_z             # (xdir,ydir) = (+,+)
    return surface_azimuth  # degree

def calc_groups(sensors_rad_clean, sensors_metadata_cat):
    """
    To calculate the mean hourly radiation of sensors in each group.

    :param sensors_rad_clean: radiation data of the filtered sensors
    :type sensors_rad_clean: dataframe
    :param sensors_metadata_cat: data of filtered sensor points categorized with module tilt angle, array spacing,
    surface azimuth, installed PV module area of each sensor point
    :type sensors_metadata_cat: dataframe
    :return number_groups: number of groups of sensor points
    :rtype number_groups: float
    :return hourlydata_groups: mean hourly radiation of sensors in each group
    :rtype hourlydata_groups: dataframe
    :return number_points: number of sensor points in each group
    :rtype number_points: array
    :return prop_observers: mean values of sensor properties of each group of sensors
    :rtype prop_observers: dataframe
    """
    # calculate number of groups as number of optimal combinations.
    groups_ob = sensors_metadata_cat.groupby(['CATB', 'CATGB', 'CATteta_z']) # group the sensors by categories
    prop_observers = groups_ob.mean().reset_index()
    prop_observers = pd.DataFrame(prop_observers)
    total_area_pv = groups_ob['area_netpv'].sum().reset_index()['area_netpv']
    prop_observers['total_area_pv'] = total_area_pv
    number_groups = groups_ob.size().count()
    sensors_list = groups_ob.groups.values()

    # calculate mean hourly radiation of sensors in each group
    rad_group_mean = np.empty(shape=(number_groups,8760))
    number_points = np.empty(shape=(number_groups,1))
    for x in range(0, number_groups):
        sensors_rad_group = sensors_rad_clean[sensors_list[x]]
        rad_mean = sensors_rad_group.mean(axis=1).as_matrix().T
        rad_group_mean[x] = rad_mean
        number_points[x] = len(sensors_list[x])
    hourlydata_groups = pd.DataFrame(rad_group_mean).T

    return number_groups, hourlydata_groups, number_points, prop_observers

#============================
#properties of module
#============================


def calc_properties_PV(type_PVpanel):
    """
    To assign PV module properties according to panel types.

    :param type_PVpanel: type of PV panel used
    :type type_PVpanel: float
    :return:
    """

    if type_PVpanel == 1:#     # assuming only monocrystalline panels.
        eff_nom = 0.16 # GTM 2014
        NOCT = 43.5 # Fanney et al.,
        Bref = 0.0035  # Fuentes et al.,Luque and Hegedus, 2003).
        a0 = 0.935823
        a1 = 0.054289
        a2 = -0.008677
        a3 = 0.000527
        a4 = -0.000011
        L = 0.002 # glazing tickness
    if type_PVpanel == 2:#     # polycristalline
        eff_nom = 0.15 # GTM 2014
        NOCT = 43.9 # Fanney et al.,
        Bref = 0.0044
        a0 = 0.918093
        a1 = 0.086257
        a2 = -0.024459
        a3 = 0.002816
        a4 = -0.000126
        L = 0.002 # glazing tickness
    if type_PVpanel == 3:#     # amorphous
        eff_nom = 0.08  # GTM 2014
        NOCT = 38.1 # Fanney et al.,
        Bref = 0.0026
        a0 = 1.10044085
        a1 = -0.06142323
        a2 = -0.00442732
        a3 = 0.000631504
        a4 = -0.000019184
        L = 0.0002 # glazing tickness

    return eff_nom,NOCT,Bref,a0,a1,a2,a3,a4,L

# investment and maintenance costs

def calc_Cinv_pv(P_peak):
    """
    To calculate capital cost of PV modules, assuming 20 year system lifetime.
    :param P_peak: installed capacity of PV module [kW]
    :return InvCa: capital cost of the installed PV module [CHF/Y]
    """
    if P_peak < 10:
        InvCa = 3500.07 * P_peak /20  #FIXME: should be amortized?
    else:
        InvCa = 2500.07 * P_peak /20

    return InvCa


# remuneration scheme

def calc_Crem_pv(E_nom):
    """
    Calculates KEV (Kostendeckende Einspeise - Verguetung) for solar PV and PVT.
    Therefore, input the nominal capacity of EACH installation and get the according KEV as return in Rp/kWh

    :param E_nom: Nominal Capacity of solar panels (PV or PVT) [Wh]
    :type E_nom: float
    :return KEV_obtained_in_RpPerkWh: KEV remuneration [Rp/kWh]
    :rtype KEV_obtained_in_RpPerkWh: float
    """

    KEV_regime = [0,
                  0,
                  20.4,
                  20.4,
                  20.4,
                  20.4,
                  20.4,
                  20.4,
                  19.7,
                  19.3,
                  19,
                  18.9,
                  18.7,
                  18.6,
                  18.5,
                  18.1,
                  17.9,
                  17.8,
                  17.8,
                  17.7,
                  17.7,
                  17.7,
                  17.6,
                  17.6]
    P_installed_in_kW = [0,
                         9.99,
                         10,
                         12,
                         15,
                         20,
                         29,
                         30,
                         40,
                         50,
                         60,
                         70,
                         80,
                         90,
                         100,
                         200,
                         300,
                         400,
                         500,
                         750,
                         1000,
                         1500,
                         2000,
                         1000000]
    KEV_interpolated_kW = interpolate.interp1d(P_installed_in_kW, KEV_regime, kind="linear")
    KEV_obtained_in_RpPerkWh = KEV_interpolated_kW(E_nom / 1000.0)
    return KEV_obtained_in_RpPerkWh


def test_photovoltaic():
    import cea.inputlocator
    import cea.globalvar

    locator = cea.inputlocator.InputLocator(r'C:\reference-case-open\baseline')
    # for the interface, the user should pick a file out of of those in ...DB/Weather/...
    weather_path = locator.get_default_weather()
    list_buildings_names = dbfreader.dbf2df(locator.get_building_occupancy())['Name']
    #pd.read_csv(locator.get_building_list()).Name.values
    gv = cea.globalvar.GlobalVariables()
    for building in list_buildings_names:
        radiation = locator.get_radiation_building(building_name= building)
        radiation_metadata = locator.get_radiation_metadata(building_name= building)
        calc_PV(locator=locator, radiation_csv= radiation, metadata_csv= radiation_metadata, latitude=46.95240555555556,
                longitude=7.439583333333333, gv=gv, weather_path=weather_path, building_name = building)

#         calc_pv_main(locator=locator, radiation = radiation, latitude=46.95240555555556, longitude=7.439583333333333, year=2014, gv=gv,
#                  weather_path=weather_path) #FIXME: check naming convention



if __name__ == '__main__':
    test_photovoltaic()