import math
import random

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from turtlesim.msg import Pose

import tkinter as tk
from tkinter import ttk

from rclpy.parameter import Parameter
from rcl_interfaces.msg import SetParametersResult
from turtlesim.srv import TeleportAbsolute

import time
from collections import deque

from std_srvs.srv import Empty
from turtlesim.srv import SetPen


class DuvarKacis(Node):
    def __init__(self):
        super().__init__('duvar_kacis')

        # Bonus: Başlatılırken değiştirilebilen parametreler.
        self.declare_parameter('ileri_hiz', 2.0)
        self.declare_parameter('donus_hiz', 2.0)
        self.declare_parameter('alt_sinir', 1.0)
        self.declare_parameter('ust_sinir', 10.0)

        self.ileri_hiz = float(self.get_parameter('ileri_hiz').value)
        self.donus_hiz = float(self.get_parameter('donus_hiz').value)
        self.alt_sinir = float(self.get_parameter('alt_sinir').value)
        self.ust_sinir = float(self.get_parameter('ust_sinir').value)

        if not 0.0 < self.alt_sinir < self.ust_sinir < 11.0:
            raise ValueError(
                'Sinirlar 0 < alt_sinir < ust_sinir < 11 olmali.'
            )

        if not 0.0 <= self.ileri_hiz <= 3.0 or not 0.2 <= self.donus_hiz <= 4.0:
            raise ValueError('Ileri hiz 0-3, donus hizi 0.2-4 arasinda olmali.')

        self.pose = None
        self.hedef_aci = None
        self.kacis_modu = False

        self.ortala_istendi = True

        self.teleport_client = self.create_client(
            TeleportAbsolute,
            '/turtle1/teleport_absolute'
        )
        
        self.kalem_client = self.create_client(
            SetPen,
            '/turtle1/set_pen'
        )

        self.temizle_client = self.create_client(
            Empty,
            '/clear'
        )

        self.cizim_kuyrugu = deque()
        self.cizim_future = None
        self.cizim_aktif = False
        self.cizim_bekle = 0.0

        self.add_on_set_parameters_callback(
            self.parametreleri_dogrula
        )

        self.yayinci = self.create_publisher(
            Twist,
            '/turtle1/cmd_vel',
            10
        )

        self.abone = self.create_subscription(
            Pose,
            '/turtle1/pose',
            self.konum_callback,
            10
        )

        # Hareket kontrolü: saniyede 20 kez.
        self.kontrol_timer = self.create_timer(
            0.05,
            self.hareket_kontrol
        )

        # Konum kaydı: saniyede bir kez.
        self.log_timer = self.create_timer(
            1.0,
            self.konum_yazdir
        )

        self.get_logger().info('Duvardan kacan kaplumbaga basladi.')

    def konum_callback(self, mesaj):
        self.pose = mesaj

    def rastgele_kacis_acisi(self):
        x = self.pose.x
        y = self.pose.y

        # Duvarlardan içeri bakan normal vektörleri.
        normaller = []

        # Köşeye yakınken komşu duvarı da hesaba kat.
        pay = min(0.3, (self.ust_sinir - self.alt_sinir) / 4.0)

        if x <= self.alt_sinir + pay:
            normaller.append((1.0, 0.0))
        if x >= self.ust_sinir - pay:
            normaller.append((-1.0, 0.0))
        if y <= self.alt_sinir + pay:
            normaller.append((0.0, 1.0))
        if y >= self.ust_sinir - pay:
            normaller.append((0.0, -1.0))

        vx = math.cos(self.pose.theta)
        vy = math.sin(self.pose.theta)

        # Geliş yönünü ilgili duvarlardan yansıt.
        for nx, ny in normaller:
            carpim = vx * nx + vy * ny
            if carpim < 0.0:
                vx -= 2.0 * carpim * nx
                vy -= 2.0 * carpim * ny

        yansima_acisi = math.atan2(vy, vx)

        # Yansıyan açıya rastgele sapma ekle.
        for _ in range(100):
            aday = yansima_acisi + random.uniform(
                -math.pi / 2.0,
                math.pi / 2.0
            )

            dx = math.cos(aday)
            dy = math.sin(aday)

            # Tüm yakın duvarlardan belirgin biçimde uzaklaşmalı.
            if all(
                dx * nx + dy * ny > 0.25
                for nx, ny in normaller
            ):
                return math.atan2(math.sin(aday), math.cos(aday))

        # Rastgele denemeler sonuç vermezse güvenli iç yönü seç.
        return math.atan2(
            sum(ny for _, ny in normaller),
            sum(nx for nx, _ in normaller)
        )

    def rastgele_hareket_kontrol(self):
        if self.pose is None:
            return

        komut = Twist()

        sinir_disinda = (
            self.pose.x < self.alt_sinir
            or self.pose.x > self.ust_sinir
            or self.pose.y < self.alt_sinir
            or self.pose.y > self.ust_sinir
        )

        # Tamamen içeri girdikten sonra yeni kaçışa hazır ol.
        if not sinir_disinda and self.hedef_aci is None:
            self.kacis_modu = False

        if sinir_disinda and not self.kacis_modu:
            self.kacis_modu = True
            self.hedef_aci = self.rastgele_kacis_acisi()

        if self.hedef_aci is not None:
            fark = self.hedef_aci - self.pose.theta
            fark = math.atan2(math.sin(fark), math.cos(fark))

            if abs(fark) > 0.05:
                # Hedefe yaklaşırken yavaşlayarak aşmayı önle.
                komut.angular.z = max(
                    -self.donus_hiz,
                    min(self.donus_hiz, 4.0 * fark)
                )
            else:
                self.hedef_aci = None
                komut.linear.x = self.ileri_hiz
        else:
            komut.linear.x = self.ileri_hiz

        self.yayinci.publish(komut)

    def konum_yazdir(self):
        if self.pose is None:
            self.get_logger().info('Konum bilgisi bekleniyor.')
            return

        self.get_logger().info(
            f'x={self.pose.x:.2f}, y={self.pose.y:.2f}'
        )
        
    def parametreleri_dogrula(self, parametreler):
        isimler = (
            'ileri_hiz',
            'donus_hiz',
            'alt_sinir',
            'ust_sinir',
        )

        degerler = {
            isim: self.get_parameter(isim).value
            for isim in isimler
        }

        for parametre in parametreler:
            if parametre.name in degerler:
                degerler[parametre.name] = parametre.value

        for deger in degerler.values():
            if (
                isinstance(deger, bool)
                or not isinstance(deger, (int, float))
                or not math.isfinite(deger)
            ):
                return SetParametersResult(
                    successful=False,
                    reason='Sonlu bir sayi girilmeli.'
                )

        if not (
            0.0 < degerler['alt_sinir']
            < degerler['ust_sinir'] < 11.0
        ):
            return SetParametersResult(
                successful=False,
                reason='0 < alt sinir < ust sinir < 11 olmali.'
            )

        if not 0.0 <= degerler['ileri_hiz'] <= 3.0:
            return SetParametersResult(
                successful=False,
                reason='Ileri hiz 0 ile 3 arasinda olmali.'
            )

        if not 0.2 <= degerler['donus_hiz'] <= 4.0:
            return SetParametersResult(
                successful=False,
                reason='Donus hizi 0.2 ile 4 arasinda olmali.'
            )

        return SetParametersResult(successful=True)

    def arayuz_parametresi_ayarla(self, degerler):
        return self.set_parameters_atomically([
            Parameter(
                name=isim,
                type_=Parameter.Type.DOUBLE,
                value=float(deger)
            )
            for isim, deger in degerler.items()
        ])
        
    def sinir_cizimini_hazirla(self):
        alt = self.alt_sinir
        ust = self.ust_sinir
        merkez = (alt + ust) / 2.0

        self.cizim_kuyrugu.clear()

        def kalem(r, g, b, kalinlik, kapali):
            istek = SetPen.Request()
            istek.r = r
            istek.g = g
            istek.b = b
            istek.width = kalinlik
            istek.off = kapali
            self.cizim_kuyrugu.append(
                (self.kalem_client, istek)
            )

        def tasi(x, y, aci=0.0):
            istek = TeleportAbsolute.Request()
            istek.x = float(x)
            istek.y = float(y)
            istek.theta = float(aci)
            self.cizim_kuyrugu.append(
                (self.teleport_client, istek)
            )

        # İlk köşeye giderken çizgi çizme.
        kalem(255, 60, 60, 3, 1)
        tasi(alt, alt)

        # Önceki çerçeveyi ve hareket izlerini temizle.
        self.cizim_kuyrugu.append(
            (self.temizle_client, Empty.Request())
        )

        # Kırmızı kalemle dört kenarı çiz.
        kalem(255, 60, 60, 3, 0)
        tasi(ust, alt)
        tasi(ust, ust)
        tasi(alt, ust)
        tasi(alt, alt)

        # Merkeze taşınırken çapraz çizgi oluşmasın.
        kalem(255, 60, 60, 3, 1)
        tasi(
            merkez,
            merkez,
            random.uniform(-math.pi, math.pi)
        )

        # Normal hareket izi için açık renkli kaleme dön.
        kalem(179, 184, 255, 2, 0)

        self.hedef_aci = None
        self.kacis_modu = False
        self.cizim_future = None
        self.cizim_bekle = 0.0
        self.cizim_aktif = True

    def sinir_cizimini_isle(self):
        # Çizim sırasında normal hareketi durdur.
        self.yayinci.publish(Twist())

        if self.cizim_future is not None:
            if not self.cizim_future.done():
                return

            try:
                self.cizim_future.result()
            except Exception as hata:
                self.get_logger().error(
                    f'Sinir cizimi basarisiz: {hata}'
                )
                self.cizim_kuyrugu.clear()
                self.cizim_future = None
                self.cizim_aktif = False

                # Bir sonraki kontrolde yeniden dene.
                self.ortala_istendi = True
                return

            self.cizim_future = None

            # Turtlesim'in konum ve kalem değişimini
            # işlemesine zaman bırak; arayüzü bloklama.
            self.cizim_bekle = time.monotonic() + 0.08
            return

        if time.monotonic() < self.cizim_bekle:
            return

        if not self.cizim_kuyrugu:
            self.cizim_aktif = False

            # Eski konumla hareket kararı verme.
            self.pose = None
            self.get_logger().info(
                'Sinirlar cizildi, kaplumbaga ortalandi.'
            )
            return

        client, istek = self.cizim_kuyrugu[0]

        if not client.service_is_ready():
            return

        self.cizim_kuyrugu.popleft()
        self.cizim_future = client.call_async(istek)

    def hareket_kontrol(self):
        # Hız değişikliklerini anında oku.
        self.ileri_hiz = float(
            self.get_parameter('ileri_hiz').value
        )
        self.donus_hiz = float(
            self.get_parameter('donus_hiz').value
        )

        alt = float(self.get_parameter('alt_sinir').value)
        ust = float(self.get_parameter('ust_sinir').value)

        if (alt, ust) != (self.alt_sinir, self.ust_sinir):
            self.alt_sinir = alt
            self.ust_sinir = ust
            self.ortala_istendi = True

        # Devam eden çerçeve tamamlanmadan yenisini başlatma.
        if self.cizim_aktif:
            self.sinir_cizimini_isle()
            return

        if self.ortala_istendi:
            self.yayinci.publish(Twist())
            self.ortala_istendi = False
            self.sinir_cizimini_hazirla()
            return

        self.rastgele_hareket_kontrol()

class HareketAlani:
    """ROS konumunu ayni pencere icindeki hareket alaninda gosterir."""

    def __init__(self, root, node):
        self.node = node
        self.izler = deque(maxlen=2500)
        self.onceki = None
        self.onceki_cizim = False
        self.onceki_sinirlar = None
        frame = ttk.Frame(root, padding=12)
        frame.pack(side='left', fill='both', expand=True)
        self.canvas = tk.Canvas(
            frame, background='#4556a5', highlightthickness=0,
            width=600, height=600
        )
        self.canvas.pack(fill='both', expand=True)
        self.bilgi = ttk.Label(frame, text='ROS konumu bekleniyor…')
        self.bilgi.pack(anchor='w', pady=(8, 0))
        self.canvas.bind('<Configure>', lambda event: self.ciz())
        root.after(40, self.guncelle)

    def guncelle(self):
        node = self.node
        sinirlar = (node.alt_sinir, node.ust_sinir)
        cizim = node.cizim_aktif or node.ortala_istendi
        if (cizim and not self.onceki_cizim) or sinirlar != self.onceki_sinirlar:
            self.izler.clear()
            self.onceki = None
        self.onceki_cizim = cizim
        self.onceki_sinirlar = sinirlar
        if node.pose is not None and not cizim:
            simdi = (node.pose.x, node.pose.y)
            if self.onceki is not None:
                mesafe = math.hypot(
                    simdi[0] - self.onceki[0], simdi[1] - self.onceki[1]
                )
                if 0.002 < mesafe < 0.5:
                    self.izler.append((self.onceki, simdi))
            self.onceki = simdi
            self.bilgi.configure(
                text=f'x: {simdi[0]:.2f}   y: {simdi[1]:.2f}   '
                     f'Yön: {math.degrees(node.pose.theta):.0f}°'
            )
        else:
            self.onceki = None
            self.bilgi.configure(text='Sınırlar hazırlanıyor…' if cizim else 'ROS konumu bekleniyor…')
        self.ciz()
        self.canvas.after(40, self.guncelle)

    def ciz(self):
        c = self.canvas
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        boyut = max(1, min(w, h) - 32)
        sol, ust = (w - boyut) / 2, (h - boyut) / 2
        olcek = boyut / 11.1

        def nokta(x, y):
            return sol + x * olcek, ust + boyut - y * olcek

        for a, b in self.izler:
            c.create_line(*nokta(*a), *nokta(*b), fill='#cbd5ff', width=2)
        alt, yuksek = self.node.alt_sinir, self.node.ust_sinir
        c.create_rectangle(
            *nokta(alt, yuksek), *nokta(yuksek, alt),
            outline='#ff6464', width=3
        )
        c.create_text(
            *nokta(alt, yuksek), anchor='sw', fill='white',
            text=f'  Sınırlar: {alt:g} – {yuksek:g}', font=('Sans', 10)
        )
        pose = self.node.pose
        if pose is None or self.node.cizim_aktif or self.node.ortala_istendi:
            return
        x, y = nokta(pose.x, pose.y)
        aci = pose.theta

        def yerel(a, b):
            return (
                x + a * math.cos(aci) - b * math.sin(aci),
                y - a * math.sin(aci) - b * math.cos(aci)
            )

        # Bas, ayaklar ve kabuk: yonu belli olan kaplumbaga simgesi.
        for a, b in [(7, 9), (7, -9), (-7, 9), (-7, -9)]:
            px, py = yerel(a, b)
            c.create_oval(px-4, py-4, px+4, py+4, fill='#8bdf86', outline='')
        px, py = yerel(15, 0)
        c.create_oval(px-6, py-6, px+6, py+6, fill='#a4ee91', outline='#244a31')
        c.create_oval(x-12, y-12, x+12, y+12, fill='#48a86b', outline='#183d30', width=2)
        c.create_polygon(
            *yerel(9, 0), *yerel(-5, 5), *yerel(-5, -5),
            fill='#d0f5a0', outline=''
        )


class KontrolPaneli:
    def __init__(self, root, node):
        self.node = node
        self.root = root

        root.title('Duvardan Kaçan Kaplumbağa')
        root.geometry('1080x680')
        root.minsize(950, 580)

        self.hareket_alani = HareketAlani(root, node)

        panel = ttk.Frame(root, padding=20)
        panel.pack(side='right', fill='y')

        ttk.Label(
            panel,
            text='Kaplumbağa ayarları',
            font=('Sans', 17, 'bold')
        ).pack(anchor='w', pady=(0, 16))

        self.durum = tk.StringVar(value='Kontrol hazır.')

        self.hiz_surgusu(
            panel, 'İleri hız', 'ileri_hiz', 0.0, 3.0
        )
        self.hiz_surgusu(
            panel, 'Dönüş hızı', 'donus_hiz', 0.2, 4.0
        )

        ttk.Separator(panel).pack(fill='x', pady=14)

        satir = ttk.Frame(panel)
        satir.pack(fill='x')

        self.alt = tk.StringVar(
            value=str(node.get_parameter('alt_sinir').value)
        )
        self.ust = tk.StringVar(
            value=str(node.get_parameter('ust_sinir').value)
        )

        ttk.Label(satir, text='Alt sınır:').grid(
            row=0, column=0, padx=(0, 8), pady=6
        )
        ttk.Entry(
            satir, textvariable=self.alt, width=10
        ).grid(row=0, column=1)

        ttk.Label(satir, text='Üst sınır:').grid(
            row=0, column=2, padx=(18, 8)
        )
        ttk.Entry(
            satir, textvariable=self.ust, width=10
        ).grid(row=0, column=3)

        ttk.Button(
            panel,
            text='Sınırları çiz ve ortala',
            command=self.sinirlari_uygula
        ).pack(fill='x', pady=12)

        ttk.Label(
            panel,
            text='Hızlar anında uygulanır.\n'
                 'İleri hız 0 olduğunda ileri hareket durur.',
            wraplength=390
        ).pack(anchor='w')

        ttk.Label(
            panel,
            textvariable=self.durum,
            wraplength=390
        ).pack(anchor='w', pady=(14, 0))

    def hiz_surgusu(self, parent, baslik, isim, alt, ust):
        deger = float(self.node.get_parameter(isim).value)

        etiket = ttk.Label(
            parent, text=f'{baslik}: {deger:.2f}'
        )
        etiket.pack(anchor='w')

        def degisti(metin):
            yeni = round(float(metin), 2)
            sonuc = self.node.arayuz_parametresi_ayarla({
                isim: yeni
            })

            if sonuc.successful:
                etiket.configure(text=f'{baslik}: {yeni:.2f}')
                self.durum.set('Hız uygulandı.')
            else:
                self.durum.set(sonuc.reason)

        surgu = ttk.Scale(
            parent,
            from_=alt,
            to=ust,
            orient='horizontal'
        )
        surgu.set(deger)
        surgu.configure(command=degisti)
        surgu.pack(fill='x', pady=(4, 12))

    def sinirlari_uygula(self):
        try:
            alt = float(self.alt.get().replace(',', '.'))
            ust = float(self.ust.get().replace(',', '.'))
        except ValueError:
            self.durum.set('Sınırlara geçerli bir sayı yaz.')
            return

        sonuc = self.node.arayuz_parametresi_ayarla({
            'alt_sinir': alt,
            'ust_sinir': ust,
        })

        if sonuc.successful:
            # Aynı değerlerle düğmeye basılsa da ortala.
            self.node.ortala_istendi = True
            self.durum.set(
                'Sınırlar uygulandı; çizim ve ortalama istendi.'
            )
        else:
            self.durum.set(sonuc.reason)

def main(args=None):
    rclpy.init(args=args)

    node = None
    root = None

    try:
        node = DuvarKacis()

        root = tk.Tk()
        KontrolPaneli(root, node)

        def ros_isle():
            if not rclpy.ok():
                root.quit()
                return

            rclpy.spin_once(node, timeout_sec=0.0)
            root.after(10, ros_isle)

        root.protocol('WM_DELETE_WINDOW', root.quit)
        root.after(10, ros_isle)
        root.mainloop()

    except KeyboardInterrupt:
        pass

    finally:
        if node is not None:
            if rclpy.ok():
                node.yayinci.publish(Twist())
            node.destroy_node()

        if root is not None:
            root.destroy()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
    


