
from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.network.urlrequest import UrlRequest
import json

KV = r"""
#:import dp kivy.metrics.dp
<RootView>:
    orientation: "vertical"
    padding: dp(12)
    spacing: dp(8)

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: dp(6)
        TextInput:
            id: server
            text: root.server_url
            multiline: False
            hint_text: "Sunucu: http://192.168.1.10:8000"
        Button:
            text: "Bağlan"
            size_hint_x: .3
            on_release: root.check_health()

    Label:
        text: root.status
        size_hint_y: None
        height: dp(32)

    Button:
        text: "PİYASAYI TARA"
        size_hint_y: None
        height: dp(52)
        disabled: root.scanning
        on_release: root.start_scan()

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(4)
        Button:
            text: "En Güçlü"
            on_release: root.show_group("top_candidates")
        Button:
            text: "Dip"
            on_release: root.show_group("dip_candidates")
        Button:
            text: "Backtest"
            on_release: root.show_group("backtest_leaders")
        Button:
            text: "Risk"
            on_release: root.show_group("risk_radar")

    ScrollView:
        do_scroll_x: False
        Label:
            id: results
            text: root.result_text
            markup: True
            text_size: self.width - dp(12), None
            size_hint_y: None
            height: self.texture_size[1] + dp(30)
            valign: "top"
"""

class RootView(BoxLayout):
    server_url = StringProperty("http://192.168.1.10:8000")
    status = StringProperty("Sunucu adresini girip Bağlan'a dokun.")
    result_text = StringProperty("Quant Scanner Mobile v1")
    scanning = False
    job_id = None
    data = {}

    def _base(self):
        return self.ids.server.text.strip().rstrip("/")

    def check_health(self):
        self.status = "Bağlantı test ediliyor..."
        UrlRequest(
            self._base()+"/health",
            on_success=lambda req,res: self._health_ok(res),
            on_failure=lambda req,res: self._err("Bağlantı kurulamadı"),
            on_error=lambda req,err: self._err(str(err)),
            timeout=10
        )

    def _health_ok(self,res):
        self.status = f"Bağlandı • {res.get('ticker_count',0)} sembol"
        self.result_text = "[b]Motor:[/b] " + str(res.get("engine",""))

    def start_scan(self):
        self.scanning = True
        self.status = "Tarama başlatılıyor..."
        UrlRequest(
            self._base()+"/scan/start",
            method="POST",
            req_body=b"",
            req_headers={"Content-Type":"application/json"},
            on_success=lambda req,res: self._job_started(res),
            on_failure=lambda req,res: self._err("Tarama başlatılamadı"),
            on_error=lambda req,err: self._err(str(err)),
            timeout=15
        )

    def _job_started(self,res):
        self.job_id = res.get("job_id")
        self.status = "Tarama çalışıyor..."
        Clock.schedule_once(lambda dt:self.poll(), 2)

    def poll(self):
        if not self.job_id: return
        UrlRequest(
            self._base()+f"/scan/status/{self.job_id}",
            on_success=lambda req,res:self._status_ok(res),
            on_failure=lambda req,res:self._err("Durum alınamadı"),
            on_error=lambda req,err:self._err(str(err)),
            timeout=12
        )

    def _status_ok(self,res):
        st=res.get("status")
        if st=="done":
            self.fetch_result()
        elif st=="error":
            self._err(res.get("error","Tarama hatası"))
        else:
            self.status="Tarama sürüyor... 714 sembol olduğu için zaman alabilir."
            Clock.schedule_once(lambda dt:self.poll(), 5)

    def fetch_result(self):
        UrlRequest(
            self._base()+f"/scan/result/{self.job_id}",
            on_success=lambda req,res:self._result_ok(res),
            on_failure=lambda req,res:self._err("Sonuç alınamadı"),
            on_error=lambda req,err:self._err(str(err)),
            timeout=20
        )

    def _result_ok(self,res):
        self.data=res
        self.scanning=False
        c=res.get("counts",{})
        self.status=f"Tamamlandı • {c.get('total_bist',0)} sembol"
        self.show_group("top_candidates")

    def show_group(self,key):
        groups={
            "top_candidates":"EN GÜÇLÜ ADAYLAR",
            "dip_candidates":"DİPTEN DÖNÜŞ ADAYLARI",
            "backtest_leaders":"BACKTEST LİDERLERİ",
            "risk_radar":"RİSK RADARI"
        }
        items=self.data.get(key,[])
        lines=[f"[b]{groups.get(key,key)}[/b]\n"]
        if not items:
            lines.append("Henüz sonuç yok.")
        for i,r in enumerate(items[:20],1):
            sym=r.get("Varlik","?")
            gp=r.get("GenelPuan","")
            risk=r.get("CakilmaRiski","")
            dip=r.get("DipPuan","")
            bt=r.get("BT_3G_Kazanma%","")
            n=r.get("BT_SinyalSayisi","")
            dec=r.get("NihaiKarar",r.get("GenelKarar",""))
            lines.append(
                f"[b]{i}. {sym}[/b]\n"
                f"Genel {gp} • Risk {risk} • Dip {dip} • 3G %{bt} (N={n})\n"
                f"{dec}\n"
            )
        self.result_text="\n".join(lines)

    def _err(self,msg):
        self.scanning=False
        self.status="Hata"
        self.result_text="[b]Hata:[/b] "+str(msg)

class QuantScannerApp(App):
    def build(self):
        self.title="Quant Scanner Mobile"
        Builder.load_string(KV)
        return RootView()

QuantScannerApp().run()
