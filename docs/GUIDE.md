# Panduan Vidyax

> Belajar Vidyax dari nol lewat contoh. Kalau butuh detail lengkap tiap
> fitur, lihat [REFERENCE.md](./REFERENCE.md).

Vidyax (`.vx`) adalah bahasa pemrograman yang dibuat supaya nulis kode
terasa seperti nulis instruksi biasa. Filosofinya: *"Code as simple as
writing instructions."*

---

## 0. Menjalankan program

Simpan kode ke file `.vx`, lalu:

```bash
vidyax run halo.vx      # cara utama menjalankan program
```

Kalau belum pasang perintah `vidyax`, jalankan langsung lewat Python:

```bash
python3 vidyax.py run halo.vx
```

---

## 1. Halo dunia

```vidyax
print "Halo, dunia!"
```

`print` menampilkan sesuatu ke layar. Teks ditulis di antara tanda kutip dua.

---

## 2. Variabel

Tanda titik dua (`:`) dipakai untuk memberi nilai ke variabel — bukan
tanda sama dengan.

```vidyax
nama: "Daf"
umur: 21
print "Halo " + nama
```

Nama built-in (seperti `len`, `get`, `print`) tidak boleh dipakai jadi
nama variabel — Vidyax akan menolaknya biar tidak bikin bingung.

---

## 3. Angka dan teks

```vidyax
print 10 + 5        # 15
print 10 / 4        # 2.5
print "a" + "b"     # ab
print "umur: " + 21 # umur: 21  (angka otomatis jadi teks saat digabung)
```

`+` menyambung teks **dan** menjumlah angka. Kalau salah satu sisi teks,
sisi lainnya ikut jadi teks.

---

## 4. Percabangan (if / elif / else)

Blok ditandai dengan indentasi (spasi menjorok), mirip Python.

```vidyax
nilai: 75

if nilai >= 90:
    print "A"
elif nilai >= 70:
    print "B"
else:
    print "C"
```

Operator logika: `and`, `or`, `not`.

```vidyax
if umur >= 17 and not false:
    print "boleh"
```

---

## 5. Perulangan

**`rpt N`** — ulang sebanyak N kali:

```vidyax
rpt 3:
    print "ulang"
```

**`for x in ...`** — jalan di tiap isi list atau tiap huruf teks:

```vidyax
buah: ["apel", "mangga", "jeruk"]
for b in buah:
    print b

for huruf in "abc":
    print huruf
```

**`break`** berhenti dari loop, **`continue`** lompat ke putaran berikutnya:

```vidyax
for i in [1, 2, 3, 4, 5]:
    if i == 4:
        break
    if i == 2:
        continue
    print i
# keluar: 1, lalu 3
```

---

## 6. Fungsi

```vidyax
func tambah(a, b):
    return a + b

print tambah(10, 20)   # 30
```

Fungsi bisa memanggil dirinya sendiri (rekursif):

```vidyax
func faktorial(n):
    if n <= 1:
        return 1
    return n * faktorial(n - 1)

print faktorial(5)   # 120
```

### Aturan variabel di dalam fungsi (penting)

Variabel yang kamu **beri nilai di dalam fungsi bersifat lokal** — cuma
hidup di fungsi itu, tidak bocor ke luar. Ini sama seperti kebanyakan
bahasa lain.

```vidyax
x: 1

func ubah():
    x: 5       # ini x LOKAL milik fungsi, bukan x di luar
    return x

print ubah()   # 5
print x        # 1  (x di luar tidak berubah)
```

Kamu tetap bisa **membaca** variabel luar selama tidak menimpanya:

```vidyax
faktor: 10

func kali(n):
    return n * faktor   # membaca 'faktor' dari luar — boleh

print kali(3)   # 30
```

Kalau butuh mengubah nilai untuk dipakai di luar, kembalikan lewat
`return` — jangan andalkan variabel global.

---

## 7. Menangani error (try / catch)

Kalau ada operasi yang bisa gagal, bungkus dengan `try` / `catch` supaya
program tidak berhenti mendadak.

```vidyax
try:
    hasil: 10 / 0
catch e:
    print "ketangkap: " + e   # ketangkap: cannot divide by 0
```

`catch` boleh tanpa variabel kalau tidak butuh pesannya:

```vidyax
try:
    print barangGaib
catch:
    print "ada yang salah, tapi program lanjut"
```

---

## 8. Input dari pengguna

`ask` membaca satu baris ketikan dari pengguna:

```vidyax
nama: ask "Siapa namamu?"
print "Halo, " + nama
```

---

## 9. Ambil data dari internet: `get`

`get(url)` mengambil isi sebuah URL sebagai teks. Kalau gagal (tidak ada
koneksi, URL salah, server error), `get` **melempar error yang bisa
ditangkap** — jadi selalu bungkus dengan `try` / `catch`.

```vidyax
try:
    kutipan: get("https://api.github.com/zen")
    print kutipan
catch e:
    print "gagal ambil data: " + e
```

> Perubahan di v1.1: dulu `get` mengembalikan teks berawalan `"ERROR_..."`
> saat gagal. Sekarang ia melempar error seperti operasi lain. Program
> lama yang mengandalkan cek `"ERROR_"` perlu diganti ke `try`/`catch`.

---

## 10. AI bawaan

Vidyax punya modul `ai` bawaan. Aktifkan dengan `use ai`, lalu bertanya
dengan `ai.ask`.

```vidyax
use ai
ai.system "jawab singkat dan santai"
jawab: ai.ask "Apa itu komputer?"
print jawab
```

Model default: `llama-3.1-8b-instant` (lewat Groq). Kamu bisa ganti model
atau penyedia:

```vidyax
ai.open "llama-3.1-8b-instant"       # ganti model (tetap Groq)
ai.open "openai:gpt-4o-mini"         # ganti penyedia + model
```

Tiap penyedia butuh API key sendiri di environment:

```bash
export GROQ_API_KEY=gsk_xxxxx
export OPENAI_API_KEY=sk_xxxxx
```

---

## Selanjutnya

- [REFERENCE.md](./REFERENCE.md) — daftar lengkap semua sintaks, fungsi
  built-in, perintah CLI, dan pesan error.
- Folder `contoh/` di repo — program contoh yang bisa langsung dijalankan.

Kalau kamu tulis program yang sama, `vidyax run` dan `vidyax walk`
harus memberi hasil identik — itu dijamin oleh test bawaan
(`vidyax test`).
