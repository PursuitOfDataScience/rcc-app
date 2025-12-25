---

Welcome to the University of Chicago RCC-GIS Geocoding Service. This application allows UChicago affiliates to take lists of street addresses or place names and convert them into latitude and longitude coordinates. The coordinate pairs can then be used in any sort of mapping application or spatial analysis method.

![University of Chicago RCC-GIS Geocoding Service](https://gis.rcc.uchicago.edu/sites/all/themes/nexus_playground/images/summaryofresponsesforweb.png)

The engine behind the RCC-GIS Geocoding Service is the [ESRI’s World Geocoder for ArcGIS](http://www.esri.com/data/find-data/worldgeocoder). The Geocoding Service has the ability to retrieve coordinates for places around the world. However, coverage does differ from country to country. Click [here](https://developers.arcgis.com/rest/geocode/api-reference/geocode-coverage.htm) to see what level of detail is available for different parts of the world. The RCC-GIS Geocoding Service is available to any UChicago affiliate with an active CNetID login and works on a credit-based system. **All users are allocated 2000 credits by default. 2000 credits will allow a user to geocode 50,000 records. If a user needs to geocode more records, a request must be forwarded by email to [gis-help@rcc.uchicago.edu](mailto:gis-help@rcc.uchicago.edu) for a larger allocation.**

## [1\. Formatting Data for Processing](https://gis.rcc.uchicago.edu/content/rcc-gis-geocoding-service#1)

Records must be formatted in a particular way for processing by the RCC-GIS Geocoding Service. The RCC-GIS Geocoding service requires data to be uploaded in a CSV (comma-separated value) format in the standard UTF-8 encoding. Different parts of the world have different formats and subdivisions for street addresses and place names. Records should be either in one column or divided accordingly for processing. The following column headers are acceptable for your CSV file:

ID
ADDRESS
NEIGHBORHOOD
CITY
SUBREGION
REGION or STATE or ST
POSTAL or ZIP or ZIPCODE
COUNTRYCODE

It is NOT necessary to provide data for all the variables listed above. However, if more data is provided, the geocoding service should provide a higher match rate.

Example File: A formatted US address file can be downloaded from [here](https://gis.rcc.uchicago.edu/sites/default/files/example_us_address.csv "example file"). 
[International address file formatting](https://www.notion.so/rccgis/International-address-file-bed388ad2beb47a49a6f5cc510f8ccf9) 
For the CSV file creation, RCC recommends the use of OpenOffice or LibreOffice over excel.

## [2\. Sign In and Execution Procedure](https://gis.rcc.uchicago.edu/content/rcc-gis-geocoding-service#link2)

Log on to the enterprise ArcGIS Online portal for the University of Chicago by clicking on **“Sign in with Enterprise Login”**.

![Choose UCHICAGO Login](https://gis.rcc.uchicago.edu/sites/all/themes/nexus_playground/images/geocoder/step1.jpg)

![Choose UCHICAGO Login](https://gis.rcc.uchicago.edu/sites/all/themes/nexus_playground/images/geocoder/step2.jpg)

![Choose UCHICAGO Login](https://gis.rcc.uchicago.edu/sites/all/themes/nexus_playground/images/geocoder/step3.jpg)

1. Enter the portal’s URL **“uchicago.maps.arcgis.com”** and click Continue.
2. Sign in to the University of Chicago portal by clicking on UCHICAGO.
3. Enter your University of Chicago CNetID username and password and click LOG IN.
4. Upload your file to be geocoded by clicking Select File.
5. Browse to your file’s location, highlight it, and click Open.
6. Click the Submit button to activate the geocoding service.
7. The geocoding service page will notify you that your file has been uploaded. Refresh your browser to see the progress with your data. _(The geocoding service will process approximately 250,000 - 500,000 records per hour.)_

When completed, click the link to Download the Geocoded File. Your geocoded file will be available for download for 7 days. After that time, it will be deleted from the queue.

## [3\. Activate Geocoding Service](https://geocoder.rcc.uchicago.edu/)

Click the above link or navigate to [http://geocoder.rcc.uchicago.edu](http://geocoder.rcc.uchicago.edu/)

## [4\. Interpreting Geocoding Output](https://gis.rcc.uchicago.edu/content/rcc-gis-geocoding-service#collapseFour)

The downloaded output file will include the user's original data along with 3 new variables, **LATITUDE**, **LONGITUDE**, and **MATCH SCORE**.

#### Latitude/Longitude

The latitude and longitude variables are the real-world coordinates as interpreted by the [ESRI’s World Geocoder for ArcGIS](http://www.esri.com/data/find-data/worldgeocoder).

#### Match Score

The match score is a calculation of how closely the interpreter came to finding the exact same address or place name. A perfect match score of 100% is optimal. However, a match score above 90% may also be suitable for many cases.

- Example: a score of 92% may occur when the user provides the following address: 1100 E. 57th, Chicago, IL. A score of 100% might have been achieved if the user included the street type (ST) in the address record. Therefore, a perfect score could be achieved for 1100 E. 57th St., Chicago, IL.

Most match scores below 90% should be scrutinized. A low match score will still produce a latitude/longitude coordinate pair but it may be incorrectly placed. If the interpreter cannot locate a street address, it defaults to the next highest location variable.

- Example: if the user has 1100 N. Woodlawn Ave., Chicago, IL as a record, the interpreter may produce a match score of 72% along with a latitude/longitude coordinate pair. However, since 1100 N. Woodlawn Ave. does not exist, the interpreter will assign the location to the center of Chicago, IL instead. IT WILL NOT PRODUCE AN ERROR, ONLY A LOWER MATCH SCORE.

**Any records with a low match score should be re-evaluated, validated with another geocoding service, or dropped from the record-set altogether.**

---

#### Note

Please refer to the FAQ section if your geocoding process fails. If you have any questions or issues with the RCC-GIS Geocoding Service, please email us: [gis-help@rcc.uchicago.edu](mailto:gis-help@rcc.uchicago.edu?Subject=Question%20regarding%20RCC-GIS%20Geocoding%20Service).

---
