import os, subprocess

c_source = """/*
 * SWEET: Qualcomm Adreno 618 GPU bring-up probe for Samsung Galaxy A71 (SM7150).
 *
 * Checks GCC bus clocks, GPUCC power domains (gpu_cx_gdsc, gpu_gx_gdsc),
 * clock branches (gpu_cc_ahb_clk, gpu_cc_gx_gfx3d_clk, gpu_cc_gmu_clk),
 * powers up the GX 3D execution domain if needed, and safely queries
 * Adreno 618 RBBM / CP registers at 0x05000000.
 */
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <pexpert/pexpert.h>

extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern void delay(int);
void sweet_gpu_probe(void);

#define GCC_PA                  0x00100000u
#define GCC_SIZE                0x00090000u
#define GCC_GPU_CFG_AHB_CBCR    0x71004u    /* AHB clock to GPUCC */
#define GCC_GPU_MEMNOC_GFX_CBCR 0x7100cu    /* MemNOC GFX clock */

#define GPUCC_PA                0x05090000u
#define GPUCC_SIZE              0x00009000u
#define GPUCC_GPU_GX_GDSCR      0x100cu     /* GX domain power switch */
#define GPUCC_GPU_CX_GDSCR      0x106cu     /* CX domain power switch */
#define GPUCC_GX_GFX3D_CBCR     0x1054u     /* 3D core clock branch */
#define GPUCC_AHB_CBCR          0x1078u     /* GPU AHB clock branch */
#define GPUCC_GMU_CBCR          0x1120u     /* GMU clock branch */

#define GDSC_SW_COLLAPSE        (1u << 0)
#define GDSC_PWR_ON             (1u << 31)
#define CBCR_CLK_OFF            (1u << 31)
#define CBCR_ENABLE             (1u << 0)

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
	for (unsigned i = 0; i < 2000; ++i) {
		uint32_t v = gpu_rd(gpucc, gdscr_off);
		if (v & GDSC_PWR_ON) {
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
	for (unsigned i = 0; i < 2000; ++i) {
		uint32_t v = gpu_rd(base, cbcr_off);
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

	PE_parse_boot_argn("sweetgpu", &enabled, sizeof(enabled));
	if (!enabled) {
		printf("SWEET GPU: disabled by sweetgpu=0\\n");
		return;
	}

	printf("SWEET GPU: probing Qualcomm Adreno 618 subsystem...\\n");

	/* 1. GCC clocks to GPU subsystem */
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

	/* 2. Map GPUCC */
	gpucc = ml_io_map(GPUCC_PA, GPUCC_SIZE);
	if (gpucc == 0) {
		printf("SWEET GPU: GPUCC map failed\\n");
		return;
	}

	cx_gdscr = gpu_rd(gpucc, GPUCC_GPU_CX_GDSCR);
	gx_gdscr = gpu_rd(gpucc, GPUCC_GPU_GX_GDSCR);
	ahb_cbcr = gpu_rd(gpucc, GPUCC_AHB_CBCR);
	gfx_cbcr = gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR);
	gmu_cbcr = gpu_rd(gpucc, GPUCC_GMU_CBCR);

	printf("SWEET GPU: initial GPUCC CX GDSC 0x%08x (%s), GX GDSC 0x%08x (%s)\\n",
	    cx_gdscr, (cx_gdscr & GDSC_PWR_ON) ? "ON" : "OFF",
	    gx_gdscr, (gx_gdscr & GDSC_PWR_ON) ? "ON" : "OFF");
	printf("SWEET GPU: initial clocks: AHB 0x%08x (%s), GFX3D 0x%08x (%s), GMU 0x%08x (%s)\\n",
	    ahb_cbcr, (ahb_cbcr & CBCR_CLK_OFF) ? "off" : "on",
	    gfx_cbcr, (gfx_cbcr & CBCR_CLK_OFF) ? "off" : "on",
	    gmu_cbcr, (gmu_cbcr & CBCR_CLK_OFF) ? "off" : "on");

	/* 3. Power on CX GDSC if needed */
	if (!(cx_gdscr & GDSC_PWR_ON)) {
		printf("SWEET GPU: powering on CX GDSC...\\n");
		gpu_wr(gpucc, GPUCC_GPU_CX_GDSCR, cx_gdscr & ~GDSC_SW_COLLAPSE);
		gpu_poll_gdsc_on(gpucc, GPUCC_GPU_CX_GDSCR, "CX");
	}

	/* 4. Power on GX GDSC if needed */
	if (!(gx_gdscr & GDSC_PWR_ON)) {
		printf("SWEET GPU: powering on GX GDSC...\\n");
		gpu_wr(gpucc, GPUCC_GPU_GX_GDSCR, gx_gdscr & ~GDSC_SW_COLLAPSE);
		gpu_poll_gdsc_on(gpucc, GPUCC_GPU_GX_GDSCR, "GX");
	}

	/* 5. Enable GPUCC AHB clock */
	if (gpu_rd(gpucc, GPUCC_AHB_CBCR) & CBCR_CLK_OFF) {
		gpu_wr(gpucc, GPUCC_AHB_CBCR, CBCR_ENABLE);
		gpu_poll_clk_on(gpucc, GPUCC_AHB_CBCR, "GPUCC AHB");
	}

	/* 6. Enable GPUCC GFX3D clock */
	if (gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR) & CBCR_CLK_OFF) {
		gpu_wr(gpucc, GPUCC_GX_GFX3D_CBCR, CBCR_ENABLE);
		delay(20);
	}

	final_gx = gpu_rd(gpucc, GPUCC_GPU_GX_GDSCR);
	final_gfx_clk = gpu_rd(gpucc, GPUCC_GX_GFX3D_CBCR);
	printf("SWEET GPU: post-power GX GDSC 0x%08x (%s), GFX3D CBCR 0x%08x (%s)\\n",
	    final_gx, (final_gx & GDSC_PWR_ON) ? "ON" : "OFF",
	    final_gfx_clk, (final_gfx_clk & CBCR_CLK_OFF) ? "off" : "on");

	/* Safety check before accessing 3D core MMIO */
	if (!(final_gx & GDSC_PWR_ON)) {
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
--- /dev/null
+++ b/bsd/dev/sweet_gpu.c
@@ -0,0 +1,""" + str(total_lines) + """ @@\n""" + '\n'.join(c_diff_lines) + '\n'

target_path = 'xnu/patches/0085-sweet-gpu-probe.patch'
with open(target_path, 'w', newline='\n') as f:
    f.write(patch_header)

print(f"Generated {target_path}: {total_lines} lines in sweet_gpu.c, total patch size: {len(patch_header)}")
