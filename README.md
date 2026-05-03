These are scripts to manage infrastructure things around AUHSD.

InformacastChecker polls our installation of Informacast to see if all the IP Speaker/Clocks are registered with Informacast. If not, it sends out an email of which ones need to be looked at.

CambiumToNetBoxToZabbix pulls all our Cambium Access Points out of Cambium Cloud, and then puts them in NetBox, and also puts them in Zabbix. If they are NOT in Zabbix, it creates them. Anything that doesn't match up in Zabbix that is in the All Access Points group gets disabled in Zabbix.\\
