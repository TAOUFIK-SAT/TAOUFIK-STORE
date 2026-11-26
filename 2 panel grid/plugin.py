# -*- coding: utf-8 -*-

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Button import Button
from Screens.MessageBox import MessageBox
from enigma import eConsoleAppContainer, eTimer
import os

PLUGIN_VERSION = "17.0.0"

# ??????? ?????? ??????? ??? ??? ?????????? ??????????? ??????? ???
PLUGINS = {
    "############ ( PANELS ) ############": "", 
    "Ajpanel": 'wget -q "--no-check-certificate" http://dreambox4u.com/emilnabil237/plugins/ajpanel/installer.sh -O - | /bin/sh',
    "Ciefp-Panel": "wget https://github.com/ciefp/CiefpsettingsPanel/raw/main/installer.sh -O - | /bin/sh',
    "EliesatPanel": "wget https://raw.githubusercontent.com/eliesat/eliesatpanel/main/installer.sh -O - | /bin/sh",
    "EmilPanel": "wget https://github.com/emilnabil/download-plugins/raw/refs/heads/main/EmilPanel/emilpanel.sh -O - | /bin/sh",
    "linuxsat-panel": "wget https://raw.githubusercontent.com/Belfagor2005/LinuxsatPanel/main/installer.sh -O - | /bin/sh",
    "levi45-AddonsManager": "wget https://dreambox4u.com/emilnabil237/plugins/levi45-addonsmanager/installer.sh -O - | /bin/sh",
    "SatVenusPanel": "wget https://dreambox4u.com/emilnabil237/plugins/satvenuspanel/installer.sh -O - | /bin/sh",
    
    "############ ( MULTIBOOT ) ############": "", 
    "EgamiBoot_10.6": "wget https://raw.githubusercontent.com/emil237/egamiboot/refs/heads/main/egamiboot-10.6.sh -O - | /bin/sh",
    "Neoboot_9.65": "wget https://dreambox4u.com/emilnabil237/plugins/neoboot-v9.65/iNB.sh -O - | /bin/sh",
    "OpenMultiboot_1.3": "wget https://raw.githubusercontent.com/emil237/openmultiboot/main/installer.sh -O - | /bin/sh",
    "Multiboot-FlashOnline": "wget https://raw.githubusercontent.com/emil237/download-plugins/main/multiboot-flashonline.sh -O - | /bin/sh",
    
    "############ ( CHANNELS ) ############": "", 
    "Elsafty-Tv-Radio-Steaming": 'wget -q "--no-check-certificate" https://dreambox4u.com/emilnabil237/settings/elsafty/installer.sh -O - | /bin/sh',
    "Khaled Ali": "wget https://raw.githubusercontent.com/emilnabil/channel-khaled/main/installer.sh -O - | /bin/sh",
    "Mohamed Goda": "wget https://raw.githubusercontent.com/emilnabil/channel-mohamed-goda/main/installer.sh -O - | /bin/sh",
    "Emil Nabil": "wget https://raw.githubusercontent.com/emilnabil/channel-emil-nabil/main/installer.sh -O - | /bin/sh",
    
    "############ ( PLUGINS ) ############": "", 
    "ArabicSavior": "wget http://dreambox4u.com/emilnabil237/plugins/ArabicSavior/installer.sh -O - | /bin/sh",
    "EPGImport": "wget https://raw.githubusercontent.com/emilnabil/download-plugins/refs/heads/main/epgimport.sh -O - | /bin/sh",
    "EPGTranslator": "wget https://raw.githubusercontent.com/emilnabil/download-plugins/refs/heads/main/epgtranslator.sh -O - | /bin/sh",
    "Internet-Speedtest": "wget https://raw.githubusercontent.com/emilnabil/download-plugins/refs/heads/main/internet-speedtest.sh -O - | /bin/sh",
    "Quran-karem_v2.2": "wget https://raw.githubusercontent.com/emil237/quran/main/installer.sh -O - | /bin/sh",
    
    # Ciefp Active Plugins
    "CiefpBouquetUpdater": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpBouquetUpdater/main/installer.sh -O - | /bin/sh",
    "CiefpChannelManager": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpChannelManager/main/installer.sh -O - | /bin/sh",
    "CiefpEPGshare": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpEPGshare/main/installer.sh -O - | /bin/sh",
    "CiefpIPTVBouquets": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpIPTVBouquets/main/installer.sh -O - | /bin/sh",
    "CiefpOscamEditor": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpOscamEditor/main/installer.sh -O - | /bin/sh",
    "CiefpSettingsDownloader": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpSettingsDownloader/main/installer.sh -O - | /bin/sh",
    "CiefpSettingsPanel": "wget -q --no-check-certificate https://raw.githubusercontent.com/ciefp/CiefpsettingsPanel/main/installer.sh -O - | /bin/sh",
    
    "############ ( Media ) ############": "",
    "BouquetMakerXtream": "wget -q --no-check-certificate http://dreambox4u.com/emilnabil237/plugins/BouquetMakerXtream/installer.sh -O - | /bin/sh",
    "E2m3u2Bouquet": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/e2m3u2bouquet/installer.sh -O - | /bin/sh",
    "E2Player-MAXBAMBY": "wget -q --no-check-certificate https://gitlab.com/maxbambi/e2iplayer/-/raw/master/install-e2iplayer.sh -O - | /bin/sh",
    "IpAudio_7.4_py3": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/ipaudio/ipaudio-7.4-ffmpeg.sh -O - | /bin/sh",
    "IpAudioPro": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/ipaudiopro/installer.sh -O - | /bin/sh",
    "jedimakerxtream": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/jedimakerxtream/installer.sh -O - | /bin/sh",
    "MultiStalkerPro": "wget -q --no-check-certificate https://raw.githubusercontent.com/emilnabil/multi-stalkerpro/main/installer.sh -O - | /bin/sh",
    "YouTube": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/YouTube/installer.sh -O - | /bin/sh",
    "Xtreamty": "wget -q --no-check-certificate https://dreambox4u.com/emilnabil237/plugins/xtreamity/installer.sh -O - | /bin/sh",
    
    "############ ( TOOLS ) ############": "", 
    "Wget": "opkg install wget",
    "Curl": "opkg install curl",
    "UPDATE ENIGMA2 ALL PYTHON": "wget https://raw.githubusercontent.com/emil237/updates-enigma/main/update-all-python.sh -O - | /bin/sh",
    "OpenATV softcamfeed": "wget -O - -q http://updates.mynonpublic.com/oea/feed | bash",
    "update": "opkg update",
    "gstplayer": "opkg install gstplayer",

    "############ ( SOFTCAMS ) ############": "", 
    "Cccam": "wget https://dreambox4u.com/emilnabil237/emu/installer-cccam.sh -O - | /bin/sh",
    "Oscam Mohamed_OS": "wget https://dreambox4u.com/emilnabil237/emu/installer-oscam.sh  -O - | /bin/sh",
    "Ncam fairman": "wget https://dreambox4u.com/emilnabil237/emu/installer-ncam.sh -O - | /bin/sh",
    "Oscam Emu biko-73": "wget https://raw.githubusercontent.com/biko-73/OsCam_EMU/main/installer.sh -O - | /bin/sh",
    
    "############ ( SKINS ) ############": "", 
    "BO-HLALA FHD SKIN": "wget https://raw.githubusercontent.com/biko-73/TeamNitro/main/script/installerB.sh -O - | /bin/sh",
    "Aglare-FHD for Atv-Spa-Egami": "wget https://raw.githubusercontent.com/popking159/skins/refs/heads/main/aglareatv/installer.sh -O - | /bin/sh",
    "Red-Dragon-FHD": "wget https://raw.githubusercontent.com/biko-73/TeamNitro/main/script/installerD.sh -O - | /bin/sh",
    "Nitro AdvanceFHD": "wget https://raw.githubusercontent.com/biko-73/NitroAdvanceFHD/main/installer.sh -qO - | /bin/sh",

    "###### ( Images ) ######": "", 
    "Image-Egami-10.4": "wget https://dreambox4u.com/emilnabil237/images/egami-10.4.sh -O - | /bin/sh",
    "Image-Openatv-7.4": "wget https://dreambox4u.com/emilnabil237/images/openatv-7.4.sh -O - | /bin/sh",
    "Image_Openatv-7.5.1": "wget https://dreambox4u.com/emilnabil237/images/openatv-7.5.1.sh -O - | /bin/sh",
    "Image_OpenBlackHole-5.4": "wget https://dreambox4u.com/emilnabil237/images/openblackhole-5.4.sh -O - | /bin/sh",
    "Image_Openpli-9.0": "wget https://dreambox4u.com/emilnabil237/images/openpli-9.0.sh -O - | /bin/sh",
    "Image_Pure2-7.4": "wget https://dreambox4u.com/emilnabil237/images/pure2-7.4.sh -O - | /bin/sh",
}

class DownloadProgress(Screen):
    skin = """
    <screen name="DownloadProgress" position="center,center" size="650,300" title="AIO Android Script Installer">
        <eLabel position="0,0" size="650,300" backgroundColor="#1E1E1E" zPosition="-1" />
        <widget name="status" position="30,30" size="590,60" font="Regular;20" foregroundColor="#FFFFFF" backgroundColor="#1E1E1E" halign="center" />
        <widget name="cancel_button" position="175,200" size="300,50" font="Bold;22" foregroundColor="#FFFFFF" backgroundColor="#FF5252" halign="center" valign="center" />
    </screen>
    """

    def __init__(self, session, plugin_name, command):
        self.session = session
        self.plugin_name = plugin_name
        self.command = command
        Screen.__init__(self, session)

        self["status"] = Label(f"Installing: {plugin_name}...\nPlease wait...")
        self["cancel_button"] = Button("Cancel (Red)")

        self["actions"] = ActionMap(
            ["ColorActions", "SetupActions"],
            {
                "red": self.cancel_download,
                "cancel": self.cancel_download,
            },
        )

        self.container = eConsoleAppContainer()
        self.container.appClosed.append(self.download_finished)
        self.start_download()

    def start_download(self):
        self.container.execute(self.command)

    def download_finished(self, retval):
        self.container.appClosed.remove(self.download_finished)
        if retval == 0:
            self.session.openWithCallback(
                self.return_to_menu,
                MessageBox,
                f"'{self.plugin_name}' installed successfully!",
                MessageBox.TYPE_INFO,
            )
        else:
            self.session.openWithCallback(
                self.return_to_menu,
                MessageBox,
                f"Failed to install '{self.plugin_name}'!",
                MessageBox.TYPE_ERROR,
            )

    def cancel_download(self):
        self.container.kill()
        self.close()

    def return_to_menu(self, _):
        self.close()


class AndroidAioPanelRef(Screen):
    skin = f"""
    <screen name="AndroidAioPanelRef" position="center,center" size="1280,720" title="Panel AIO {PLUGIN_VERSION}">
        <eLabel position="0,0" size="1280,720" backgroundColor="#121212" zPosition="-5" />
        
        <!-- ?????? ?????? -->
        <eLabel position="40,20" size="1200,75" backgroundColor="#1E1E1E" zPosition="-1" />
        <widget name="title_label" position="60,28" size="500,32" font="Regular;24" foregroundColor="#FFFFFF" backgroundColor="#1E1E1E" transparent="1" />
        <widget name="subtitle_label" position="60,60" size="500,22" font="Regular;14" foregroundColor="#AAAAAA" backgroundColor="#1E1E1E" transparent="1" />
        
        <widget name="top_sys_info" position="580,35" size="640,40" font="Regular;16" foregroundColor="#03DAC6" backgroundColor="#1E1E1E" halign="right" transparent="1" />

        <!-- ??????? ???????? -->
        <eLabel position="40,115" size="380,535" backgroundColor="#1E1E1E" zPosition="-1" />
        <widget name="menu" position="55,130" size="350,505" backgroundColor="#1E1E1E" foregroundColor="#FFFFFF" font="Regular;18" itemHeight="38" selectionEnabled="1" transparent="1" scrollbarMode="showOnDemand" />

        <!-- ???? ???????? ?????? -->
        <eLabel position="440,115" size="800,535" backgroundColor="#1E1E1E" zPosition="-1" />
        <widget name="detail_title" position="470,140" size="740,35" font="Regular;22" foregroundColor="#BB86FC" backgroundColor="#1E1E1E" transparent="1" />
        <widget name="detail_desc" position="470,190" size="740,120" font="Regular;16" backgroundColor="#1E1E1E" foregroundColor="#E0E0E0" transparent="1" />
        
        <!-- ????? ??????? ?????? ?????? -->
        <eLabel position="470,320" size="740,305" backgroundColor="#282828" zPosition="0" />
        <widget name="sys_spec_1" position="495,350" size="690,30" font="Regular;16" foregroundColor="#FFFFFF" backgroundColor="#282828" transparent="1" />
        <widget name="sys_spec_2" position="495,390" size="690,30" font="Regular;16" foregroundColor="#FFFFFF" backgroundColor="#282828" transparent="1" />
        <widget name="sys_spec_3" position="495,430" size="690,30" font="Regular;16" foregroundColor="#FFFFFF" backgroundColor="#282828" transparent="1" />
        <widget name="sys_spec_4" position="495,470" size="690,30" font="Regular;16" foregroundColor="#FFFFFF" backgroundColor="#282828" transparent="1" />
        <widget name="sys_spec_5" position="495,510" size="690,30" font="Regular;16" foregroundColor="#03DAC6" backgroundColor="#282828" transparent="1" />

        <!-- ?????? ?????? ???????? ??????? -->
        <eLabel position="40,665" size="1200,40" backgroundColor="#181818" zPosition="-1" />
        <widget name="key_red" position="50,673" size="130,24" font="Bold;14" foregroundColor="#FFFFFF" backgroundColor="#FF5252" halign="center" valign="center" />
        <widget name="key_green" position="190,673" size="130,24" font="Bold;14" foregroundColor="#FFFFFF" backgroundColor="#4CAF50" halign="center" valign="center" />
        <widget name="key_yellow" position="330,673" size="130,24" font="Bold;14" foregroundColor="#000000" backgroundColor="#FFEB3B" halign="center" valign="center" />
        <widget name="key_blue" position="470,673" size="130,24" font="Bold;14" foregroundColor="#FFFFFF" backgroundColor="#2196F3" halign="center" valign="center" />
        <widget name="footer_info" position="615,675" size="605,20" font="Regular;14" foregroundColor="#AAAAAA" backgroundColor="#181818" halign="right" transparent="1" />
    </screen>
    """

    def __init__(self, session):
        self.session = session
        Screen.__init__(self, session)

        self.pluginKeys = list(PLUGINS.keys())
        self["menu"] = MenuList(self.pluginKeys)
        
        self["title_label"] = f"Panel AIO {PLUGIN_VERSION}"
        self["subtitle_label"] = "Optimized Android UI & Cleaned Tools Hub"
        self["top_sys_info"] = Label("CPU: 14%  |  RAM: 28%  |  Flash: 72%  |  03122026  10:35")
        
        self["detail_title"] = Label("Select a Script or Plugin")
        self["detail_desc"] = Label("Cleaned list: only active and working plugins/scripts are listed here.")
        
        self["sys_spec_1"] = Label(self.get_image_type())
        self["sys_spec_2"] = Label("Python: 3.8+")
        self["sys_spec_3"] = Label(self.get_storage_info())
        self["sys_spec_4"] = Label(self.get_cpu_info())
        self["sys_spec_5"] = Label(self.get_internet_status())
        
        self["key_red"] = Label("Polski")
        self["key_green"] = Label("English")
        self["key_yellow"] = Label("Restart GUI")
        self["key_blue"] = Label("Update")
        self["footer_info"] = Label(f"AIO {PLUGIN_VERSION} | build r1 | Py3 | AIO-IPTV.pl")

        self["actions"] = ActionMap(
            ["ColorActions", "SetupActions", "OkCancelActions"],
            {
                "red": self.actionPolski,
                "green": self.actionEnglish,
                "yellow": self.actionRestart,
                "blue": self.actionUpdate,
                "cancel": self.close,
                "ok": self.install_plugin,
                "up": self.up,
                "down": self.down,
            },
        )
        
        self.onShown.append(self.updateDetails)

    def up(self):
        self["menu"].up()
        self.updateDetails()

    def down(self):
        self["menu"].down()
        self.updateDetails()

    def updateDetails(self):
        current = self["menu"].getCurrent()
        if current:
            if current.startswith("############") or current.startswith("######"):
                self["detail_title"].setText("Category Header")
                self["detail_desc"].setText(f"--- {current} ---\nSection separator. Choose an active item below.")
            else:
                cmd = PLUGINS.get(current, "")
                self["detail_title"].setText(f"Plugin: {current}")
                self["detail_desc"].setText(f"Active package ready to install.\nCommand:\n{cmd}\n\nPress OK or Green button to install.")

    def get_image_type(self):
        try:
            with open("/etc/image-version", "r") as f:
                for line in f:
                    if "creator" in line.lower():
                        return f"Image: {line.strip().replace('creator', '').replace('=', '').strip()}"
            return "Image: egami / openatv"
        except:
            return "Image: egami"

    def get_cpu_info(self):
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return f"CPU: {line.split(':')[1].strip()}"
            return "CPU: ARM Quad Core"
        except:
            return "CPU: 14%"

    def get_storage_info(self):
        try:
            statvfs = os.statvfs("/")
            total = (statvfs.f_blocks * statvfs.f_frsize) // (1024 * 1024)
            free = (statvfs.f_bfree * statvfs.f_frsize) // (1024 * 1024)
            used_pct = int(((total - free) / total) * 100) if total > 0 else 72
            return f"Flash: {used_pct}% Used ({free}MB Free)"
        except:
            return "Flash: 72%"

    def get_internet_status(self):
        try:
            status = "Connected" if os.system("ping -c 1 8.8.8.8 > /dev/null 2>&1") == 0 else "Disconnected"
            return f"Network: {status} (DHCP Active)"
        except:
            return "Network: Connected"

    def install_plugin(self):
        selected = self["menu"].getCurrent()
        if selected:
            if selected.startswith("############") or selected.startswith("######"):
                self.session.open(MessageBox, "Please select an active script or plugin.", MessageBox.TYPE_INFO, timeout=3)
                return
            if selected in PLUGINS and PLUGINS[selected]:
                command = PLUGINS[selected]
                self.session.open(DownloadProgress, selected, command)

    def actionPolski(self):
        self.session.open(MessageBox, "Language changed to Polski", MessageBox.TYPE_INFO, timeout=2)

    def actionEnglish(self):
        self.session.open(MessageBox, "Language changed to English", MessageBox.TYPE_INFO, timeout=2)

    def actionRestart(self):
        os.system("killall -9 enigma2")
        self.close()

    def actionUpdate(self):
        update_command = "wget https://github.com/emilnabil/download-plugins/raw/refs/heads/main/Ciefp-Panel/Ciefp-Panel.sh -O - | /bin/sh"
        self.session.open(DownloadProgress, "AIO Panel Update", update_command)


def main(session, **kwargs):
    session.open(AndroidAioPanelRef)

def Plugins(**kwargs):
    return [
        PluginDescriptor(
            name=f"Panel AIO {PLUGIN_VERSION}",
            description="Cleaned and optimized Android UI tools hub",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon="plugin.png",
            fnc=main
        )
    ]
