REM script used to test the cea by the jenkins for each pull request
SET CEA=%USERPROFILE%\Documents\CityEnergyAnalyst
SET PATH=%CEA%\Dependencies\Python;%CEA%\Dependencies\Python\Scripts;%CEA%\Dependencies\Daysim;%PATH%
SET PYTHONHOME=%CEA%\Dependencies\Python
SET PYTHONHOME=%CEA%\Dependencies\Python
SET GDAL_DATA=%CEA%\Dependencies\Python\Library\share\gdal
SET PROJ_LIB=%CEA%\Dependencies\Python\Library\share
SET RAYPATH=%CEA%\Dependencies\Daysim
"%CEA%\Dependencies\Python\python.exe" -u -m pip install -e .

"%CEA%\Dependencies\Python\python.exe" -u -m cea.interfaces.cli.cli test --workflow quick

if %errorlevel% neq 0 exit /b %errorlevel%
