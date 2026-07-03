# Referensi Bahasa Vidyax (v1.1)

Dokumen ini mendaftar seluruh sintaks, tipe, fungsi built-in, perintah
CLI, dan pesan error Vidyax. Untuk belajar dari nol, lihat
[GUIDE.md](./GUIDE.md).

---

## Model eksekusi

Vidyax punya **dua mesin eksekusi yang berbagi satu runtime**:

| Perintah      | Mesin                | Keterangan |
|---------------|----------------------|------------|
| `vidyax run`  | transpiler → Python  | jalur utama; menerjemahkan `.vx` ke Python lalu menjalankannya |
| `vidyax walk` | tree-walker          | menafsirkan pohon sintaks langsung; berguna untuk debug/pembanding |

Keduanya memanggil helper runtime yang sama, jadi hasilnya identik secara
konstruksi. Kesamaan ini diuji otomatis: `vidyax test` menjalankan tiap
kasus di **kedua** mesin dan mengharuskan outputnya sama persis.

---

## Sintaks dasar

- Satu pernyataan per baris. Tidak ada titik koma.
- Blok ditandai **indentasi** (menjorok dengan spasi), seperti Python.
- Komentar diawali `#` sampai akhir baris.

```vidyax
# ini komentar
print "halo"
```

---

## Tipe nilai

| Tipe    | Contoh literal          | Catatan |
|---------|-------------------------|---------|
| angka   | `42`, `3.14`, `-7`      | integer & desimal dipakai bersama |
| teks    | `"halo"`                | kutip dua |
| boolean | `true`, `false`         |         |
| kosong  | `null`                  | ketiadaan nilai |
| list    | `[1, 2, 3]`, `["a","b"]`| boleh campur tipe |

`type(x)` mengembalikan nama tipe sebagai teks: `"number"`, `"text"`,
`"bool"`, `"null"`, atau `"list"`.

---

## Variabel

```vidyax
nama: nilai
```

- Assignment memakai `:` (bukan `=`).
- Nama fungsi built-in **dilarang** dipakai sebagai nama variabel, nama
  fungsi, parameter, variabel loop, atau variabel `catch`. Ini menghindari
  ketidakcocokan antar-mesin dan langsung ketahuan lewat `vidyax check`.
- **Aturan cakupan (scope):** nama yang diberi nilai di dalam sebuah
  fungsi bersifat **lokal** ke fungsi itu. Membaca variabel lokal sebelum
  ia diberi nilai adalah error. Membaca nama yang tidak pernah di-assign
  lokal akan mencari ke cakupan luar (bisa baca variabel global).

---

## Operator

**Aritmatika:** `+`  `-`  `*`  `/`  `%`

- `+` menyambung teks maupun menjumlah angka. Jika salah satu sisi teks,
  sisi lain otomatis dikonversi ke teks.
- `+` juga menggabung dua list.
- `/` selalu menghasilkan desimal; pembagian oleh nol → error
  `cannot divide by 0`.

**Perbandingan:** `==`  `!=`  `<`  `<=`  `>`  `>=` → menghasilkan boolean.

**Logika:** `and`  `or`  `not`.

**Indeks:** `list[i]` atau `teks[i]`, dihitung dari 0. Indeks di luar
jangkauan → error `index out of range`.

**Akses anggota:** `objek.anggota`. Hanya modul runtime Vidyax (yaitu
`ai`) yang punya anggota. Anggota berawalan garis bawah (`_`) tidak bisa
diakses (mencegah bocornya internal Python).

---

## Percabangan

```vidyax
if kondisi:
    ...
elif kondisi_lain:
    ...
else:
    ...
```

`elif` dan `else` opsional. Nilai dianggap "benar" bila: boolean `true`,
angka bukan nol, teks/list tidak kosong.

---

## Perulangan

**Ulang N kali** — `N` harus angka (kalau bukan → `'rpt' needs a number`):

```vidyax
rpt N:
    ...
```

**Iterasi list atau teks** — sumber harus list/teks (kalau bukan →
`'for ... in' needs a list or text`):

```vidyax
for item in sumber:
    ...
```

**Kontrol loop:**

- `break` — keluar dari loop.
- `continue` — lanjut ke putaran berikutnya.

`break`/`continue` di luar loop adalah error saat *parse*
(`'break' only works inside a loop`). `break` di dalam fungsi tidak bisa
menembus ke loop di luar fungsi.

---

## Fungsi

```vidyax
func nama(p1, p2):
    ...
    return nilai
```

- `return` boleh tanpa nilai (mengembalikan `null`), atau dengan nilai.
- `return` di luar fungsi adalah error saat parse
  (`'return' only works inside a function`).
- Jumlah argumen harus cocok dengan jumlah parameter; kalau tidak →
  `function 'nama' needs N args, got M`.
- Fungsi rekursif didukung.

---

## Penanganan error

```vidyax
try:
    ...
catch e:      # 'e' berisi pesan error sebagai teks
    ...
```

Variabel `catch` opsional:

```vidyax
try:
    ...
catch:
    ...
```

Semua error runtime (bagi nol, indeks lewat, `get` gagal, dll.) bisa
ditangkap. Pesan error sama persis di kedua mesin eksekusi.

---

## Input

```vidyax
ask "pertanyaan"
```

Menampilkan prompt dan membaca satu baris ketikan pengguna sebagai teks.

```vidyax
umur: ask "Berapa umurmu?"
```

---

## Fungsi built-in

| Fungsi              | Hasil |
|---------------------|-------|
| `len(x)`            | panjang teks atau list |
| `range(n)`          | list `[0, 1, ..., n-1]` |
| `range(a, b)`       | list `[a, ..., b-1]` |
| `text(x)`           | ubah nilai ke teks |
| `num(x)`            | ubah teks/nilai ke angka |
| `upper(s)`          | teks jadi HURUF BESAR |
| `lower(s)`          | teks jadi huruf kecil |
| `split(s, sep=" ")` | pecah teks jadi list berdasarkan pemisah |
| `join(lst, sep="")` | gabung list jadi teks dengan pemisah |
| `push(lst, x)`      | tambah `x` ke akhir list |
| `abs(x)`            | nilai mutlak |
| `sum(x)`            | jumlah semua isi list |
| `min(...)`          | nilai terkecil |
| `max(...)`          | nilai terbesar |
| `type(x)`           | nama tipe sebagai teks |
| `get(url)`          | ambil isi URL sebagai teks (lempar error saat gagal) |

Nama-nama di atas bersifat *reserved* — tidak bisa ditimpa.

---

## Modul `ai`

Aktifkan dengan `use ai`. Objek `ai` muncul di lingkup program.

| Anggota            | Fungsi |
|--------------------|--------|
| `ai.ask "..."`     | kirim prompt, kembalikan jawaban sebagai teks |
| `ai.system "..."`  | set instruksi sistem (persona/aturan) |
| `ai.open "..."`    | ganti model atau penyedia |
| `ai.model`         | nama model aktif |
| `ai.provider`      | nama penyedia aktif (`groq` / `openai`) |
| `ai.system_prompt` | isi instruksi sistem aktif |

**Format `ai.open`:**

- `ai.open "nama-model"` — ganti model, penyedia tetap.
- `ai.open "penyedia:model"` — ganti keduanya, mis. `"openai:gpt-4o-mini"`.

Default: penyedia `groq`, model `llama-3.1-8b-instant`. Bisa diubah lewat
environment `VIDYAX_MODEL`.

**API key** (per penyedia):

| Penyedia | Environment      | URL |
|----------|------------------|-----|
| groq     | `GROQ_API_KEY`   | api.groq.com |
| openai   | `OPENAI_API_KEY` | api.openai.com |

Penyedia tak dikenal → `unknown AI provider`. Key belum di-set → pesan
yang menyebut nama environment yang dibutuhkan.

---

## Perintah CLI

| Perintah                 | Fungsi |
|--------------------------|--------|
| `vidyax run <file.vx>`   | jalankan program (jalur transpiler; default) |
| `vidyax walk <file.vx>`  | jalankan lewat tree-walker |
| `vidyax build <file.vx>` | terjemahkan ke file Python `.py` mandiri |
| `vidyax check <file.vx>` | cek statis saja, keluarkan error dalam JSON (`-` = stdin) |
| `vidyax test`            | jalankan test bawaan (di kedua mesin) |
| `vidyax <file.vx>`       | sama dengan `run` |

Menjalankan tanpa argumen membuka REPL interaktif.

Perintah roadmap (dikenali tapi belum jalan): `fmt`, `install`, dan kata
kunci `agent`, `go`, `use web`, `use database`.

---

## Katalog pesan error

| Pesan | Sebab |
|-------|-------|
| `variable 'X' is not defined` | membaca variabel yang belum ada |
| `variable 'X' is assigned in this function but used before it has a value` | membaca variabel lokal sebelum diberi nilai |
| `'X' is a built-in function name — pick a different name` | menimpa nama built-in |
| `cannot divide by 0` | pembagian oleh nol |
| `index out of range` | indeks list/teks di luar jangkauan |
| `'rpt' needs a number` | `rpt` dengan nilai non-angka |
| `'for ... in' needs a list or text` | iterasi sumber non-list/teks |
| `this is not a function` | memanggil nilai yang bukan fungsi |
| `function 'X' needs N args, got M` | jumlah argumen salah |
| `member 'X' is private` | akses anggota berawalan `_` |
| `object has no member 'X'` | akses anggota pada nilai yang tak punya anggota |
| `'ai' has no member 'X'` | anggota `ai` tak dikenal |
| `unknown AI provider 'X'` | penyedia AI tak dikenal |
| `'break' only works inside a loop` | `break`/`continue` di luar loop |
| `'return' only works inside a function` | `return` di luar fungsi |
| `get() failed: ...` | `get(url)` gagal (koneksi/HTTP) |

Semua pesan konsisten antara `run` dan `walk`.

---

## Kata kunci (reserved words)

```
print  if  elif  else  rpt  for  in  func  return
ask  use  and  or  not  true  false  null
break  continue  try  catch
agent  go        # roadmap, belum jalan
```
