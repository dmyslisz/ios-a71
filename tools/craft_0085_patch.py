import os, subprocess

rpmh_diff = '--- a/bsd/dev/sweet_rpmh.c\n+++ b/bsd/dev/sweet_rpmh.c\n@@ -11,6 +11,7 @@\n #include <machine/machine_routines.h>\n \n extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);\n+int sweet_rpmh_arc_vote(const char *res, uint32_t level);\n int sweet_rpmh_vreg_enable(const char *res, unsigned mv);\n \n /* Live downstream DT has two positional reg entries, no reg-names. */\n@@ -324,6 +325,160 @@ rh_send(uint32_t address, unsigned mv)\n \treturn 0;\n }\n \n+static int\n+rh_lookup_arc(const char *res, uint32_t *address)\n+{\n+\tuint32_t key[2] = {0, 0};\n+\tunsigned matches = 0;\n+\tunsigned i = 0, j = 0;\n+\n+\tfor (i = 0; i < 8 && res[i]; ++i) {\n+\t\tkey[i / 4] |= (uint32_t)(uint8_t)res[i] << (8u * (i % 4));\n+\t}\n+\tfor (i = 0; i < 8; ++i) {\n+\t\tuint32_t h = 8u + 16u * i;\n+\t\tunsigned slave = rh_db16(h);\n+\t\tuint32_t entries = 0, aux = 0;\n+\t\tunsigned count = 0;\n+\n+\t\tif (!slave) {\n+\t\t\tbreak;\n+\t\t}\n+\t\tif (slave != 3u) {\n+\t\t\tcontinue;\n+\t\t}\n+\t\tentries = RH_DB_HEADER + rh_db16(h + 2);\n+\t\taux = RH_DB_HEADER + rh_db16(h + 4);\n+\t\tcount = rh_db16(h + 6);\n+\t\tif ((entries & 3u) || !rh_range(entries, count * RH_DB_ENTRY) || !rh_range(aux, 0)) {\n+\t\t\tprintf("SWEET RPMH: malformed ARC slave header %u\\n", i);\n+\t\t\treturn EINVAL;\n+\t\t}\n+\t\tfor (j = 0; j < count; ++j) {\n+\t\t\tuint32_t e = entries + RH_DB_ENTRY * j;\n+\t\t\tuint32_t addr = 0;\n+\t\t\tif (rh_read(rh_db, e) != key[0] || rh_read(rh_db, e + 4) != key[1]) {\n+\t\t\t\tcontinue;\n+\t\t\t}\n+\t\t\taddr = rh_read(rh_db, e + 16);\n+\t\t\t*address = addr;\n+\t\t\t++matches;\n+\t\t\tprintf("SWEET RPMH: ARC %s addr=0x%08x slave=%u\\n", res, addr, slave);\n+\t\t}\n+\t}\n+\tif (matches != 1) {\n+\t\tprintf("SWEET RPMH: ARC %s lookup matches=%u\\n", res, matches);\n+\t\treturn ENODEV;\n+\t}\n+\treturn 0;\n+}\n+\n+static int\n+rh_send_arc(uint32_t address, uint32_t level)\n+{\n+\tint chosen = -1;\n+\tunsigned t = 0, us = 0;\n+\tuint32_t b = 0, bit = 0, irq_en = 0, cmd = 0, status = 0;\n+\tbool done = false;\n+\n+\tfor (t = 0; t < RH_ACTIVE_N; ++t) {\n+\t\tif (rh_free(t)) {\n+\t\t\tchosen = (int)t;\n+\t\t\tbreak;\n+\t\t}\n+\t}\n+\tif (chosen < 0) {\n+\t\tprintf("SWEET RPMH: no empty idle ACTIVE TCS for ARC\\n");\n+\t\treturn EBUSY;\n+\t}\n+\tt = (unsigned)chosen;\n+\tb = t * RH_TCS_STRIDE;\n+\tbit = 1u << t;\n+\tirq_en = rh_read(rh_tcs, RH_IRQ_EN);\n+\tif (irq_en == 0xffffffffu || !rh_free(t)) {\n+\t\treturn EBUSY;\n+\t}\n+\tif (!rh_sync(RH_IRQ_EN, irq_en & ~bit)) {\n+\t\trh_poisoned = true;\n+\t\treturn EIO;\n+\t}\n+\tif (!rh_free(t)) {\n+\t\tif (!rh_sync(RH_IRQ_EN, (rh_read(rh_tcs, RH_IRQ_EN) & ~bit) | (irq_en & bit))) {\n+\t\t\trh_poisoned = true;\n+\t\t}\n+\t\treturn EBUSY;\n+\t}\n+\trh_poisoned = true;\n+\tprintf("SWEET RPMH: TCS%u ARC addr=0x%08x level=%u\\n", t, address, level);\n+\tcmd = b;\n+\tif (!rh_sync(cmd + RH_MSGID, RH_WRITE_ACK) ||\n+\t    !rh_sync(cmd + RH_ADDR, address) ||\n+\t    !rh_sync(cmd + RH_DATA, level)) {\n+\t\treturn EIO;\n+\t}\n+\tif (!rh_sync(b + RH_WAIT, 1) || !rh_sync(b + RH_ENABLE, 1) ||\n+\t    !rh_sync(b + RH_CONTROL, 0) || !rh_sync(b + RH_CONTROL, RH_AMC_EN)) {\n+\t\treturn EIO;\n+\t}\n+\trh_write(rh_tcs, b + RH_CONTROL, RH_AMC_EN | RH_TRIGGER);\n+\tfor (us = 0; us < RH_TIMEOUT_US; ++us) {\n+\t\tstatus = rh_read(rh_tcs, b + RH_CMD_STATUS);\n+\t\tif (status != 0xffffffffu &&\n+\t\t    (status & (RH_ISSUED | RH_COMPLETE)) == (RH_ISSUED | RH_COMPLETE)) {\n+\t\t\tdone = true;\n+\t\t\tbreak;\n+\t\t}\n+\t\tdelay(1);\n+\t}\n+\tif (!done) {\n+\t\tprintf("SWEET RPMH: ARC timeout addr=0x%08x status=0x%08x\\n", address, status);\n+\t\treturn ETIMEDOUT;\n+\t}\n+\tif (!rh_sync(b + RH_CONTROL, RH_AMC_EN) || !rh_sync(b + RH_CONTROL, 0) ||\n+\t    !rh_sync(b + RH_ENABLE, 0) || !rh_sync(b + RH_WAIT, 0)) {\n+\t\treturn EIO;\n+\t}\n+\trh_write(rh_tcs, RH_IRQ_CLEAR, bit);\n+\tif ((rh_read(rh_tcs, RH_IRQ_STATUS) & bit) ||\n+\t    !rh_sync(RH_IRQ_EN, (rh_read(rh_tcs, RH_IRQ_EN) & ~bit) | (irq_en & bit))) {\n+\t\treturn EIO;\n+\t}\n+\trh_poisoned = false;\n+\tprintf("SWEET RPMH: ARC vote complete\\n");\n+\treturn 0;\n+}\n+\n+int\n+sweet_rpmh_arc_vote(const char *res, uint32_t level)\n+{\n+\tint error = EIO;\n+\tuint32_t address = 0;\n+\n+\tif (!res || level > 512) {\n+\t\treturn EINVAL;\n+\t}\n+\tif (__atomic_exchange_n(&rh_lock, 1, __ATOMIC_ACQUIRE)) {\n+\t\treturn EBUSY;\n+\t}\n+\tif (rh_poisoned) {\n+\t\tprintf("SWEET RPMH: previous uncertain transaction; refusing further access\\n");\n+\t\tgoto out;\n+\t}\n+\terror = rh_map();\n+\tif (!error) {\n+\t\terror = rh_lookup_arc(res, &address);\n+\t}\n+\tif (!error) {\n+\t\terror = rh_send_arc(address, level);\n+\t}\n+out:\n+\tif (error) {\n+\t\tprintf("SWEET RPMH: arc vote %s failed errno=%d\\n", res, error);\n+\t}\n+\t__atomic_store_n(&rh_lock, 0, __ATOMIC_RELEASE);\n+\treturn error;\n+}\n+\n int\n sweet_rpmh_vreg_enable(const char *res, unsigned mv)\n {\n'

# 2. sweet_gpu.c C source code
c_source = """/*
 * SWEET: Qualcomm Adreno 618 GPU bring-up probe for Samsung Galaxy A71 (SM7150).
 *
 * Votes RPMh voltage rails (cx.lvl, mx.lvl, gfx.lvl), checks GCC bus clocks,
 * enables GPUCC AHB branch, powers up CX GDSC, pulses AON reset, force-enables
 * GFX3D root clock, powers up GX GDSC, enables GFX3D clock branch, and safely
 * reads Adreno 618 RBBM / CP registers at 0x05000000.
 */
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <pexpert/pexpert.h>

extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern void delay(int);
extern int sweet_rpmh_arc_vote(const char *res, uint32_t level);
void sweet_gpu_probe(void);

#define GCC_PA                  0x00100000u
#define GCC_SIZE                0x00090000u
#define GCC_GPU_CFG_AHB_CBCR    0x71004u    /* AHB clock to GPUCC */
#define GCC_GPU_MEMNOC_GFX_CBCR 0x7100cu    /* MemNOC GFX clock */

#define GPUCC_PA                0x05090000u
#define GPUCC_SIZE              0x00009000u
#define GPUCC_GPU_GX_GDSCR      0x100cu     /* GX domain power switch */
#define GPUCC_GPU_CX_GDSCR      0x106cu     /* CX domain power switch */
#define GPUCC_GX_GFX3D_CMD_RCGR 0x101cu     /* GFX3D root clock RCG command */
#define GPUCC_GX_SW_RESET       0x1008u     /* GX AON logic reset */
#define GPUCC_GX_GFX3D_CBCR     0x1054u     /* 3D core clock branch */
#define GPUCC_AHB_CBCR          0x1078u     /* GPU AHB clock branch */
#define GPUCC_GMU_CBCR          0x1120u     /* GMU clock branch */

#define GDSC_SW_COLLAPSE        (1u << 0)
#define GDSC_PWR_ON             (1u << 31)
#define GDSC_PWR_UP_DONE        (1u << 16)
#define CBCR_CLK_OFF            (1u << 31)
#define CBCR_ENABLE             (1u << 0)
#define RCG_ROOT_EN             (1u << 1)

#define KGSL_3D0_PA             0x05000000u
#define KGSL_3D0_SIZE           0x00040000u

/* Adreno 6xx RBBM & CP register byte offsets (dwords << 2) */
#define A6XX_RBBM_STATUS              (0x210u << 2) /* 0x0840 */
#define A6XX_RBBM_STATUS3             (0x213u << 2) /* 0x084c */
#define A6XX_RBBM_VBIF_GX_RESET_STATUS (0x215u << 2) /* 0x0854 */
#define A6XX_CP_RB_BASE               (0x800u << 2) /* 0x2000 */

#define GMU_PA                  0x0506a000u
#define GMU_SIZE                0x00001000u

static inline uint32_t
gpu_rd(vm_offset_t base, uint32_t off)
{
	uint32_t v = *(volatile uint32_t *)(base + off);
	__asm__ volatile ("dmb oshld" ::: "memory");
	return v;
}

static inline void
gpu_wr(vm_offset_t base, uint32_t off, uint32_t val)
{
	*(volatile uint32_t *)(base + off) = val;
	__asm__ volatile ("dmb oshst" ::: "memory");
}

static bool
gpu_poll_gdsc_on(vm_offset_t gpucc, uint32_t gdscr_off, const char *name)
{
	unsigned i = 0;
	uint32_t v = 0;

	for (i = 0; i < 2000; ++i) {
		v = gpu_rd(gpucc, gdscr_off);
		if (v & (GDSC_PWR_ON | GDSC_PWR_UP_DONE)) {
			return true;
		}
		delay(5);
	}
	printf("SWEET GPU: %s GDSC power-on timed out (0x%08x)\\n", name, gpu_rd(gpucc, gdscr_off));
	return false;
}

static bool
gpu_poll_clk_on(vm_offset_t base, uint32_t cbcr_off, const char *name)
{
	unsigned i = 0;
	uint32_t v = 0;

	for (i = 0; i < 2000; ++i) {
		v = gpu_rd(base, cbcr_off);
		if (!(v & CBCR_CLK_OFF)) {
			return true;
		}
		delay(5);
	}
	printf("SWEET GPU: %s clock enable timed out (0x%08x)\\n", name, gpu_rd(base, cbcr_off));
	return false;
}

void
sweet_gpu_probe(void)
{
	int enabled = 1;
	vm_offset_t gcc = 0, gpucc = 0, kgsl = 0, gmu = 0;
	uint32_t gcc_ahb = 0, gcc_memnoc = 0;
	uint32_t cx_gdscr = 0, gx_gdscr = 0;
	uint32_t ahb_cbcr = 0, gfx_cbcr = 0, gmu_cbcr = 0;
	uint32_t final_gx = 0, final_gfx_clk = 0;
	uint32_t rbbm_status = 0, rbbm_status3 = 0, vbif_reset = 0, cp_rb_base = 0;
	int arc_cx = 0, arc_mx = 0, arc_gfx = 0;

	PE_parse_boot_argn("sweetgpu", &enabled, sizeof(enabled));
	if (!enabled) {
		printf("SWEET GPU: disabled by sweetgpu=0\\n");
		return;
	}

	printf("SWEET GPU: probing Qualcomm Adreno 618 subsystem...\\n");

	/* 1. Vote RPMh voltage rails: cx.lvl, mx.lvl, gfx.lvl (128 = SVS level) */
	arc_cx = sweet_rpmh_arc_vote("cx.lvl", 128);
	arc_mx = sweet_rpmh_arc_vote("mx.lvl", 128);
	arc_gfx = sweet_rpmh_arc_vote("gfx.lvl", 128);
	printf("SWEET GPU: RPMh ARC votes: cx=%d mx=%d gfx=%d\\n", arc_cx, arc_mx, arc_gfx);

	/* 2. GCC clocks to GPU subsystem */
	gcc = ml_io_map(GCC_PA, GCC_SIZE);
	if (gcc == 0) {
		printf("SWEET GPU: GCC map failed\\n");
		return;
	}
	gcc_ahb = gpu_rd(gcc, GCC_GPU_CFG_AHB_CBCR);
	gcc_memnoc = gpu_rd(gcc, GCC_GPU_MEMNOC_GFX_CBCR);
	printf("SWEET GPU: GCC AHB CBCR 0x%08x (%s), MemNOC CBCR 0x%08x (%s)\\n",
	    gcc_ahb, (gcc_ahb & CBCR_CLK_OFF) ? "off" : "on",
	    gcc_memnoc, (gcc_memnoc & CBCR_CLK_OFF) ? "off" : "on");

	/* Enable GCC AHB clock if off */
	if (gcc_ahb & CBCR_CLK_OFF) {
		gpu_wr(gcc, GCC_GPU_CFG_AHB_CBCR, gcc_ahb | CBCR_ENABLE);
		gpu_poll_clk_on(gcc, GCC_GPU_CFG_AHB_CBCR, "GCC AHB");
	}
	if (gcc_memnoc & CBCR_CLK_OFF) {
		gpu_wr(gcc, GCC_GPU_MEMNOC_GFX_CBCR, gcc_memnoc | CBCR_ENABLE);
		gpu_poll_clk_on(gcc, GCC_GPU_MEMNOC_GFX_CBCR, "GCC MemNOC");
	}

	/* 3. Map GPUCC and enable GPU AHB clock branch */
	gpucc = ml_io_map(GPUCC_PA, GPUCC_SIZE);
	if (gpucc == 0) {
		printf("SWEET GPU: GPUCC map failed\\n");
		return;
	}

	ahb_cbcr = gpu_rd(gpucc, GPUCC_AHB_CBCR);
	if (ahb_cbcr & CBCR_CLK_OFF) {
		printf("SWEET GPU: enabling GPUCC AHB branch...\\n");
		gpu_wr(gpucc, GPUCC_AHB_CBCR, CBCR_ENABLE);
		gpu_poll_clk_on(gpucc, GPUCC_AHB_CBCR, "GPUCC AHB");
	}

	cx_gdscr = gpu_rd(gpucc, GPUCC_GPU_CX_GDSCR);
	gx_gdscr = gpu_rd(gpucc, GPUCC_GPU_GX_GDSCR);
	gfx_cbcr = gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR);
	gmu_cbcr = gpu_rd(gpucc, GPUCC_GMU_CBCR);

	printf("SWEET GPU: initial GPUCC CX GDSC 0x%08x (%s), GX GDSC 0x%08x (%s)\\n",
	    cx_gdscr, (cx_gdscr & GDSC_PWR_ON) ? "ON" : "OFF",
	    gx_gdscr, (gx_gdscr & GDSC_PWR_ON) ? "ON" : "OFF");
	printf("SWEET GPU: initial clocks: AHB 0x%08x (%s), GFX3D 0x%08x (%s), GMU 0x%08x (%s)\\n",
	    gpu_rd(gpucc, GPUCC_AHB_CBCR), (gpu_rd(gpucc, GPUCC_AHB_CBCR) & CBCR_CLK_OFF) ? "off" : "on",
	    gfx_cbcr, (gfx_cbcr & CBCR_CLK_OFF) ? "off" : "on",
	    gmu_cbcr, (gmu_cbcr & CBCR_CLK_OFF) ? "off" : "on");

	/* 4. Power on CX GDSC if needed */
	if (!(cx_gdscr & GDSC_PWR_ON)) {
		printf("SWEET GPU: powering on CX GDSC...\\n");
		gpu_wr(gpucc, GPUCC_GPU_CX_GDSCR, cx_gdscr & ~GDSC_SW_COLLAPSE);
		gpu_poll_gdsc_on(gpucc, GPUCC_GPU_CX_GDSCR, "CX");
	}

	/* 5. Prerequisites for GX GDSC */
	/* 5a. Force-enable root clock (gpu_cc_gx_gfx3d_clk_src at 0x101c) */
	printf("SWEET GPU: force-enabling GFX3D root clock (0x101c)...\\n");
	gpu_wr(gpucc, GPUCC_GX_GFX3D_CMD_RCGR, gpu_rd(gpucc, GPUCC_GX_GFX3D_CMD_RCGR) | RCG_ROOT_EN);
	delay(20);

	/* 5b. Pulse AON reset (sw-reset at 0x1008) */
	printf("SWEET GPU: pulsing AON logic reset (0x1008)...\\n");
	gpu_wr(gpucc, GPUCC_GX_SW_RESET, 1u);
	delay(20);
	gpu_wr(gpucc, GPUCC_GX_SW_RESET, 0u);
	delay(20);

	/* 5c. Power on GX GDSC */
	gx_gdscr = gpu_rd(gpucc, GPUCC_GPU_GX_GDSCR);
	if (!(gx_gdscr & (GDSC_PWR_ON | GDSC_PWR_UP_DONE))) {
		printf("SWEET GPU: powering on GX GDSC (current: 0x%08x)...\\n", gx_gdscr);
		gpu_wr(gpucc, GPUCC_GPU_GX_GDSCR, gx_gdscr & ~GDSC_SW_COLLAPSE);
		gpu_poll_gdsc_on(gpucc, GPUCC_GPU_GX_GDSCR, "GX");
	}

	/* 6. Enable GPUCC GFX3D branch clock */
	if (gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR) & CBCR_CLK_OFF) {
		printf("SWEET GPU: enabling GFX3D branch clock...\\n");
		gpu_wr(gpucc, GPUCC_GX_GFX3D_CBCR, CBCR_ENABLE);
		delay(20);
	}

	final_gx = gpu_rd(gpucc, GPUCC_GPU_GX_GDSCR);
	final_gfx_clk = gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR);
	printf("SWEET GPU: post-power GX GDSC 0x%08x (%s, pwr_up_done=%d), GFX3D CBCR 0x%08x (%s)\\n",
	    final_gx, (final_gx & GDSC_PWR_ON) ? "ON" : "OFF",
	    !!(final_gx & GDSC_PWR_UP_DONE),
	    final_gfx_clk, (final_gfx_clk & CBCR_CLK_OFF) ? "off" : "on");

	/* Safety check before accessing 3D core MMIO */
	if (!(final_gx & (GDSC_PWR_ON | GDSC_PWR_UP_DONE))) {
		printf("SWEET GPU: GX GDSC not powered; skipping KGSL 3D MMIO access\\n");
		return;
	}

	/* 7. Map and read Adreno 618 3D Core */
	kgsl = ml_io_map(KGSL_3D0_PA, KGSL_3D0_SIZE);
	if (kgsl == 0) {
		printf("SWEET GPU: KGSL 3D map failed\\n");
		return;
	}

	rbbm_status = gpu_rd(kgsl, A6XX_RBBM_STATUS);
	rbbm_status3 = gpu_rd(kgsl, A6XX_RBBM_STATUS3);
	vbif_reset = gpu_rd(kgsl, A6XX_RBBM_VBIF_GX_RESET_STATUS);
	cp_rb_base = gpu_rd(kgsl, A6XX_CP_RB_BASE);

	printf("SWEET GPU: Adreno 618 core responding!\\n");
	printf("SWEET GPU: RBBM_STATUS=0x%08x, STATUS3=0x%08x, VBIF_RESET=0x%08x, CP_RB_BASE=0x%08x\\n",
	    rbbm_status, rbbm_status3, vbif_reset, cp_rb_base);

	/* 8. Map and inspect GMU (Cortex-M4 management unit) */
	gmu = ml_io_map(GMU_PA, GMU_SIZE);
	if (gmu != 0) {
		printf("SWEET GPU: GMU mapped at 0x%lx (reg0=0x%08x, reg4=0x%08x)\\n",
		    (unsigned long)gmu, gpu_rd(gmu, 0), gpu_rd(gmu, 4));
	}
}
#endif /* ARM64_BOARD_CONFIG_SWEET */"""

lines = c_source.strip().splitlines()
c_diff_lines = [f"+{l}" for l in lines]
total_lines = len(c_diff_lines)

patch_header = """--- a/bsd/conf/files
+++ b/bsd/conf/files
@@ -111,6 +111,7 @@
 bsd/dev/sweet_rpmh.c			standard
 bsd/dev/sweet_spmi.c			standard
 bsd/dev/sweet_usb.c			standard
+bsd/dev/sweet_gpu.c			standard
 bsd/dev/mem.c				standard
 bsd/dev/munge.c 			optional config_requires_u32_munging
 bsd/dev/unix_startup.c			standard
--- a/bsd/dev/sweet_ufs.c
+++ b/bsd/dev/sweet_ufs.c
@@ -53,6 +53,7 @@ extern void sweet_sample_start(void);
 extern void sweet_keys_init(void);
 extern void sweet_touch_init(void);
 extern void sweet_usb_probe(void);
+extern void sweet_gpu_probe(void);
 
 #define REG_CAP         0x00
 #define REG_IS          0x20
@@ -660,5 +661,6 @@ sweet_ufs_init(void)
 	sweet_keys_init();
 	sweet_touch_init();
 	sweet_usb_probe();
+	sweet_gpu_probe();
 	return 0;
 }
""" + rpmh_diff + """--- /dev/null
+++ b/bsd/dev/sweet_gpu.c
@@ -0,0 +1,""" + str(total_lines) + """ @@\n""" + '\n'.join(c_diff_lines) + '\n'

target_path = 'xnu/patches/0085-sweet-gpu-probe.patch'
with open(target_path, 'w', newline='\n') as f:
    f.write(patch_header)

print(f"Generated {target_path}: {total_lines} lines in sweet_gpu.c, total patch size: {len(patch_header)}")
