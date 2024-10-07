
City Energy Analyst (CEA) Fork: Contributions from the Cooling Singapore Project (CS2.0)
==========================================================================================

This repository is a fork of the City Energy Analyst (CEA) and includes developments made as part of the
**`Cooling Singapore project (CS2.0) <https://sec.ethz.ch/research/cs.html>`_**.
Like other repositories within this organization, this fork serves as one of the core building blocks
of the Digital Urban Climate Twin (DUCT), developed under CS2.0. The DUCT integrates several computational models to
simulate urban heat and assess heat mitigation strategies in Singapore.

The primary goal of these developments is to assess anthropogenic heat emissions from buildings within DUCT, providing
insights into their contribution to Singapore's urban heat island (UHI) effect.

Key Contributions
=================

The main contributions of this forked branch can be summarized as follows:

1. **Updated Database for Singapore's Modern Building Energy Efficiency Standards**

   This database reflects two key building energy efficiency standards in Singapore:

   - **Baseline**: Represents the built environment as of 2023.
   - **SLE (Super Low Energy)**: An aspirational standard for energy efficiency.

   The data was derived from a sensitivity study on building parameters, designed to find the best fits for real energy
   demand profiles in residential, commercial, and office buildings. The results were condensed to form the two energy
   efficiency standards.

   - **Main Contributor**: `@lguilhermers <https://github.com/lguilhermers>`_
   - **Core File Location**: ``cea/databases/SG_SLE``

2. **New Input Parameters for Anthropogenic Heat Profiles**

   This contribution introduces new input parameters and functions for creating anthropogenic heat profiles for user-defined
   sampling dates. The generated profiles can be found in:

   - ``CEA_project\CEA_scenario\outputs\data\emissions\AH``

   These profiles consist of 24-hour data (hourly time steps) for each thermal network and non-connected building in the
   analyzed domain. They serve as an input for the PALM4-U microclimate model, linking CEA with PALM4-U to study urban
   microclimates.

   - **Main Contributor**: `@MatNif <https://github.com/MatNif>`_
   - **Core File Locations**:
     - ``cea/demand/anthropogenic_heat_emissions.py``
     - ``cea/optimization_new/domain.py``
     - ``cea/default.config``

3. **Integration of Distributed Renewable Energy Generation into Thermal Network Optimization**

   This development expands the optimization algorithm to include the sizing of distributed renewable energy generation
   technologies (e.g., photovoltaic and solar thermal rooftops). The optimization now considers:

   - Renewable energy generation capacities as decision variables.
   - The integration of geospatial data from OpenStreetMap (OSM) for optimizing renewable energy potential (e.g., for
     water bodies and geothermal energy).

   These enhancements allow users to identify the most effective locations for distributed renewable energy generation based
   on the chosen objective functions (e.g., cost, GHG emissions, anthropogenic heat emissions, and energy demand).

   - **Main Contributor**: `@peppenappi <https://github.com/peppenappi>`_
   - **Core File Locations**:
     - ``cea/resources``
     - ``cea/optimization_new``

4. **Analysis of Pharmaceutical and Semiconductor Production Facilities**

   This feature extends the previously implemented process-cooling systems (originally developed for data centers) to two
   additional industrial sectors: pharmaceutical and semiconductor production facilities.

   - **Main Contributor**: `@YiKaiTsai <https://github.com/YiKaiTsai>`_
   - **Core File Location**:
     - ``cea/demand/datacenter_loads.py``


How to Use This Fork
====================

To explore the contributions described above, you can start by examining the core file locations specified for each feature.
The changes are modular and designed to support CEA's existing workflows, with extensions to provide better insights into
energy demand, emissions, and optimization in the context of urban heat island mitigation and distributed renewable energy.

