# T9015 Playback DTS Patches

## Краткие патчи для быстрого применения

### Patch 1: Активация базовых аудио узлов в meson-g12a-superbird.dts

Добавить в конец файла (перед `/`):

```dts
/* ===== T9015 PLAYBACK ENABLE ===== */

/* Активируем audio clock controller */
&clkc_audio {
	status = "okay";
};

/* Активируем audio arbiter */
&arb {
	status = "okay";
};

/* Активируем T9015 codec */
&acodec {
	status = "okay";
};

/* Активируем TDM интерфейс A (опционально, если нужен) */
&tdmif_a {
	status = "okay";
	pinctrl-names = "default";
	pinctrl-0 = <&tdmout_a_pins>;
};

/* ===== / T9015 PLAYBACK ENABLE ===== */
```

---

### Patch 2: Модификация sound узла

Заменить существующий `sound` узел на:

```dts
sound {
	compatible = "amlogic,axg-sound-card";
	model = "SUPERBIRD";
	audio-routing = 
		"TODDR_A IN 4", "PDM Capture",
		"ACODEC OUT", "Speaker";
	assigned-clocks = <&clkc CLKID_MPLL2>,
			  <&clkc CLKID_MPLL0>,
			  <&clkc CLKID_MPLL1>;
	assigned-clock-parents = <0>, <0>, <0>;
	assigned-clock-rates = <294912000>,
				   <270950400>,
				   <393216000>;
	status = "okay";

	dai-link-0 {
		sound-dai = <&toddr_a>;
	};

	dai-link-1 {
		sound-dai = <&pdm>;
		codec {
			sound-dai = <&dmics>;
		};
	};

	/* ===== T9015 PLAYBACK LINK ===== */
	dai-link-2 {
		sound-dai = <&toddr_a>;
		codec {
			sound-dai = <&acodec>;
		};
	};
	/* ===== / T9015 PLAYBACK LINK ===== */
};
```

---

### Patch 3: Альтернативный вариант через TDM (если TOACODEC не работает)

Если вариант с `toddr_a` не работает, попробовать через `tdmif_a`:

```dts
sound {
	compatible = "amlogic,axg-sound-card";
	model = "SUPERBIRD";
	audio-routing = 
		"TDM_A OUT", "Speaker",
		"TODDR_A IN 4", "PDM Capture";
	// ... остальное ...

	dai-link-2 {
		sound-dai = <&tdmif_a>;  /* Используем TDM вместо TODDR */
		codec {
			sound-dai = <&acodec>;
		};
	};
};
```

---

## Полный пример модифицированного sound узла

Для наглядности - полный sound узел с T9015 playback:

```dts
sound {
	compatible = "amlogic,axg-sound-card";
	model = "SUPERBIRD";
	audio-routing = 
		"TODDR_A IN 4", "PDM Capture",
		"ACODEC OUT", "Speaker",
		"ACODEC OUT", "Headphone";
	assigned-clocks = <&clkc CLKID_MPLL2>,
			  <&clkc CLKID_MPLL0>,
			  <&clkc CLKID_MPLL1>;
	assigned-clock-parents = <0>, <0>, <0>;
	assigned-clock-rates = <294912000>,
				   <270950400>,
				   <393216000>;
	status = "okay";

	/* Capture from PDM (microphones) */
	dai-link-0 {
		sound-dai = <&toddr_a>;
	};

	/* Capture from PDM to DMIC codec */
	dai-link-1 {
		sound-dai = <&pdm>;
		codec {
			sound-dai = <&dmics>;
		};
	};

	/* Playback through T9015 codec */
	dai-link-2 {
		sound-dai = <&toddr_a>;
		codec {
			sound-dai = <&acodec>;
		};
	};
};
```

---

## Вариант из superbird-patched-audio-v1.dts (Альтернативный подход)

Если стандартный подход не работает, можно использовать альтернативную структуру из патчедного файла:

```dts
/* Добавить отдельный t9015 узел (альтернатива acodec) */
t9015 {
	#sound-dai-cells = <0>;
	compatible = "amlogic, aml_codec_T9015";
	reg = <0x0 0xff632000 0x0 0x2000>;
	is_auge_used = <1>;
	tdmout_index = <0>;
	status = "okay";
};

/* Добавить tdma узел если его нет */
&audiobus {
	tdma {
		compatible = "amlogic, g12a-snd-tdma";
		#sound-dai-cells = <0>;
		// ... другие свойства ...
		status = "okay";
	};
};

/* Модифицированный sound узел */
auge_sound {
	compatible = "amlogic, g12a-sound-card";
	aml-audio-card,name = "AML-AUGESOUND";
	aml-audio-card,loopback = <&loopback>;
	aml-audio-card,aux-devs = <&t9015>;
	avout_mute-gpios = <&gpio GPIOX_2 GPIO_ACTIVE_LOW>;
	
	aml-audio-card,dai-link@0 {
		format = "i2s";
		mclk-fs = <256>;
		suffix-name = "alsaPORT-i2s";
		cpu {
			sound-dai = <&tdma>;
			dai-tdm-slot-tx-mask = <1 1>;
			dai-tdm-slot-rx-mask = <1 1>;
			dai-tdm-slot-num = <2>;
			dai-tdm-slot-width = <32>;
			system-clock-frequency = <12288000>;
		};
		codec {
			sound-dai = <&t9015>;
		};
	};
};
```

**Примечание**: Этот вариант требует большего количества изменений в DTS, так как использует кастомные свойства Amlogic (`aml-audio-card,*`). Лучше сначала попробовать стандартный подход через `acodec` узел.

---

## Проверка применённых изменений

После применения патчей и компиляции:

```bash
# Проверить, что acodec узел включен в DTB
dtc -I dtb -O dts arch/arm64/boot/dts/amlogic/meson-g12a-superbird.dtb | grep -A10 "acodec@"

# Проверить, что sound узел содержит dai-link-2
dtc -I dtb -O dts arch/arm64/boot/dts/amlogic/meson-g12a-superbird.dtb | grep -A5 "dai-link-2"

# Проверить, что status = "okay" для нужных узлов
dtc -I dtb -O dts arch/arm64/boot/dts/amlogic/meson-g12a-superbird.dtb | grep -B2 "status = \"okay\"" | grep -E "(acodec|clkc_audio|arb|tdmif)"
```

---

## Резюме

### Минимальные изменения (рекомендуется):
1. Добавить `&acodec { status = "okay"; }`
2. Добавить `&clkc_audio { status = "okay"; }`
3. Добавить `&arb { status = "okay"; }`
4. Добавить `dai-link-2` в sound узел

### Альтернативные изменения (если не работает):
- Использовать `tdmif_a` вместо `toddr_a`
- Создать отдельный `t9015` узел (как в superbird-patched-audio-v1.dts)
- Использовать кастомные Amlogic свойства

---

*Эти патчи можно применять непосредственно к meson-g12a-superbird.dts*
