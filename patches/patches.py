from .patch import Patches
from math import ceil, floor


def _round_down_word(val):
    return (val // 4) * 4

def _round_up_word(val):
    return ceil(val  / 4) * 4

def _round_down_page(val):
    return (val // 4096) * 4096

def _round_up_page(val):
    return ceil(val  / 4096) * 4096

def _seconds_to_frames(seconds):
    return int(round(60 * seconds))

def add_patch_args(parser):
    parser.add_argument("--disable-sleep", action="store_true",
                        help="Disables sleep timer")
    parser.add_argument("--sleep-time", type=float, default=None,
                        help="Go to sleep after this many seconds of inactivity.. "
                         "Valid range: [1, 1092]"
                        )
    parser.add_argument("--hard-reset-time", type=float, default=None,
                         help="Hold power button for this many seconds to perform hard reset."
                         )
    parser.add_argument("--mario-song-time", type=float, default=None,
                         help="Hold the A button for this many seconds on the time "
                         "screen to launch the mario drawing song easter egg."
                         )
    parser.add_argument("--slim", action="store_true", default=False,
                        help="Remove mario song from extflash")


def patch_args_validation(parser, args):
    if args.disable_sleep and args.sleep_time:
        parser.error("Conflicting options: cannot specify both --disable-sleep and --sleep-time")
    if args.sleep_time and (args.sleep_time < 1 or args.sleep_time > 1092):
        parser.error("--sleep-time must be in range [1, 1092]")
    if args.mario_song_time and (args.mario_song_time < 1 or args.mario_song_time > 1092):
        parser.error("--mario_song-time must be in range [1, 1092]")


def _relocate_external_functions(offset):
    """
    data start: 0x900bfd1c
    fn start: 0x900c0258
    fn end:   0x900c34c0
    fn len: 12904
    """
    patches = Patches()

    references = [
        0x00d330,
        0x00d310,
        0x00d308,
        0x00d338,
        0x00d348,
        0x00d360,
        0x00d368,
        0x00d388,
        0x00d358,
        0x00d320,
        0x00d350,
        0x00d380,
        0x00d378,
        0x00d318,
        0x00d390,
        0x00d370,
        0x00d340,
        0x00d398,
        0x00d328,

        0x900c1174,
        0x900c313c,
        0x900c049c,
        0x900c1178,
        0x900c220c,
        0x900c3490,
        0x900c3498,
    ]
    for i, reference in enumerate(references):
        patches.append("add", reference, offset, size=4,
                       message=f"Update code references {i} at {hex(reference)}")
    patches.append("move", 0x900bfd1c, offset, size=14244)

    return patches

def parse_patches(args):
    patches = Patches()

    int_addr_start = 0x0800_0000  # TODO: get this from int_firmware
    int_pos = 0x1_D000  # TODO: this might change if more custom code is added

    patches.append("replace", 0x4, "bootloader",
                   message="Invoke custom bootloader prior to calling stock Reset_Handler")
    patches.append("bl", 0x6b52, "read_buttons",
                   message="Intercept button presses for macros")

    if args.hard_reset_time:
        hard_reset_time_ms = int(round(args.hard_reset_time * 1000))
        patches.append("ks_thumb", 0x9cee, f"movw r1, #{hard_reset_time_ms}", size=4,
                       message=f"Hold power button for {hard_reset_time_ms} "
                                "milliseconds to perform hard reset.")

    if args.sleep_time:
        sleep_time_frames = _seconds_to_frames(args.sleep_time)
        patches.append("ks_thumb", 0x6c3c, f"movw r2, #{sleep_time_frames}", size=4,
                       message=f"Setting sleep time to {args.sleep_time} seconds.")

    if args.disable_sleep:
        patches.append("replace", 0x6C40, 0x91, size=1,
                       message=f"Disable sleep timer")

    if args.mario_song_time:
        mario_song_frames = _seconds_to_frames(args.mario_song_time)
        patches.append("ks_thumb", 0x6fc4, f"cmp.w r0, #{mario_song_frames}", size=4,
                       message=f"Setting Mario Song time to {args.mario_song_time} seconds.")

    if False:
        patches.append("ks_thumb", 0x135de, "and r1, r1, #0x7F", size=4,
                       message="Disable watchdog WWDG.")

    if args.slim:
        offset = 0

        mario_song_len = 0x85e40  # 548,416 bytes
        # This isn't really necessary, but we keep it here because its more explicit.
        patches.append("replace", 0x9001_2D44, b"\x00" * (mario_song_len),
                       message="Erasing Mario Song")
        # Note, bytes starting at 0x90012ca4 leading up to the mario song
        # are also empty.
        offset -= mario_song_len

        # Each tile is 16x16 pixels, stored as 256 bytes in row-major form.
        # These index into a palette. TODO: where is the palette
        # Moving this to internal firmware for now as a PoC.
        compressed_tile_len = 5356
        patches.append("compress", 0x9009_8b84, 0x1_0000, size=compressed_tile_len,
                       message="Compress time tiles.")
        patches.append("bl", 0x678e, "memcpy_inflate")
        patches.append("move_to_int", 0x9009_8b84, int_pos, size=compressed_tile_len,
                       message="Moving custom clock graphics to internal firmware.")
        patches.append("replace", 0x7350, int_addr_start + int_pos, size=4,
                       message="Update custom clock graphics references")

        compressed_tile_len = _round_up_word(compressed_tile_len)
        int_pos += compressed_tile_len
        offset -= 0x1_0000

        # Note: the clock uses a different palette; this palette only applies
        # to ingame Super Mario Bros 1 & 2
        patches.append("move", 0x900a_8b84, offset, size=192,
                       message="Move NES emulator palette.")
        patches.append("add", 0xb720, offset, size=4,
                       message="Update NES emulator palette references.")

        # Note: UNKNOWN* represents a block of data that i haven't decoded
        # yet. If you know what the block of data is, please let me know!
        patches.append("move", 0x900a_8c44, offset, size=8352,
                       message="Move UNKNOWN1")
        patches.append("add", 0xbc44, offset, size=4,
                       message=f"Update UNKNOWN1 references")

        #patches.append("move", 0x900a_ace4, offset, size=9088,
        patches.append("move", 0x900a_ace4, offset, size=9088,
                       message="Move GAME menu icons 1.")
        patches.append("add", 0xcea8, offset, size=4,
                       message=f"Update GAME menu icons references")

        patches.append("move", 0x900a_d064, offset, size=7040,
                       message="Move GAME menu icons 2.")
        patches.append("add", 0xd2f8, offset, size=4,
                       message=f"Update GAME menu icons references")


        patches.append("move", 0x900a_ebe4, offset, size=116,
                       message="Move menu stuff (icons? meta?)")
        references = [
            0x0_d010,
            0x0_d004,
            0x0_d2d8,
            0x0_d2dc,
            0x0_d2f4,
            0x0_d2f0,
        ]
        for i, reference in enumerate(references):
            patches.append("add", reference, offset, size=4,
                           message=f"Update menu references {i} at {hex(reference)}")


        # I think the memcpy code should only be 65536 long.
        # stock firmware copies 122_880, like halfway into the mario juggling pic
        compressed_mario_2 = 42917
        patches.append("compress", 0x900a_ec58, 0x1_0000, size=compressed_mario_2,
                       message="Compress Mario 2 ROM.")
        patches.append("bl", 0x6a12, "memcpy_inflate")
        patches.append("move", 0x900a_ec58, offset, size=compressed_mario_2,
                       message="Move mario 2 rom")
        patches.append("add", 0x0_7374, offset, size=4,
                       message="Update Mario 2 ROM reference")

        compressed_mario_2 = _round_up_word(compressed_mario_2)
        offset -= (65536 - compressed_mario_2)  # Move by the space savings.

        # Round to nearest page so that the length can be used as an imm
        compressed_mario_2 = _round_up_page(compressed_mario_2)

        patches.append("ks_thumb", 0x6a0a, f"mov.w r2, #{compressed_mario_2}", size=4,
                       message="Fix bug? Mario 2 ROM is only 65536 long.")
        patches.append("ks_thumb", 0x6a1e, f"mov.w r3, #{compressed_mario_2}", size=4,
                       message="Fix bug? Mario 2 ROM is only 65536 long.")

        # Not sure what this data is
        patches.append("move", 0x900bec58, offset, size=8 * 2,
                       message="Two sets of uint8_t[8]. Not sure what they represent.")
        patches.append("add", 0x1_0964, offset, size=4,
                       message="Two sets of uint8_t[8]. Not sure what they represent.")



        # These somehow describe the time scenes (impacts how all background is drawn)
        patches.append("move", 0x900bec68, offset, size=320,
                       message="Time generic scene [0600, 1700)")
        patches.append("move", 0x900beda8, offset, size=320,
                       message="Time generic scene [1800, 0400)")
        patches.append("move", 0x900beee8, offset, size=320,
                        message="Time underwater scene (between 1200 and 2400 at XX:30)")
        patches.append("move", 0x900bf028, offset, size=320,
                       message="Time unknown scene")
        patches.append("move", 0x900bf168, offset, size=320,
                       message="Time dawn scene [0500, 0600)")
        #               message="Underground coin bonus scene (between 0000 and 1200 at XX:30)")

        # These might be 8x8 2-bpp sprites?
        eight_bytes_start = 0x900bf2a8
        eight_bytes_end   = 0x900bf410
        eight_bytes_len = eight_bytes_end - eight_bytes_start
        for addr in range(eight_bytes_start, eight_bytes_end, 8):
            patches.append("move", addr, offset, size=8)


        # IDK what this is.
        patches.append("move", 0x900bf410, offset, size=144)
        patches.append("add", 0x1_658c, offset, size=4)


        # This table is related to time events.
        lookup_table_start = 0x900b_f4a0
        lookup_table_end   = 0x900b_f838
        lookup_table_len   = lookup_table_end - lookup_table_start  # 920
        def cond(addr):
            # Return True if it's beyond the mario song addr
            return 0x9001_2D44 <= addr
        for addr in range(lookup_table_start, lookup_table_end, 4):
            patches.append("add", addr, offset, size=4, cond=cond)
        # Now move the table
        patches.append("move", lookup_table_start, offset, size=lookup_table_len,
                       message="Moving event lookup table")
        patches.append("add", 0xdf88, offset, size=4,
                       message="Updating event lookup table reference")


        patches.append("move", 0x900bf838, offset, size=280,)
        patches.append("add", 0xe8f8, offset, size=4)
        patches.append("add", 0xf4ec, offset, size=4)
        patches.append("add", 0xf4f8, offset, size=4)
        patches.append("add", 0x10098, offset, size=4)
        patches.append("add", 0x105b0, offset, size=4)


        patches.append("move", 0x900bf950, offset, size=180,)
        patches.append("add", 0xe2e4, offset, size=4)
        patches.append("add", 0xf4fc, offset, size=4)


        patches.append("move", 0x900bfa04, offset, size=8,)
        patches.append("add", 0x1_6590, offset, size=4)

        patches.append("move", 0x900bfa0c, offset, size=784,)
        patches.append("add", 0x1_0f9c, offset, size=4)


        patches.extend(_relocate_external_functions(offset))


        patches.append("move", 0x900c34c0, offset, size=6168)
        patches.append("add", 0x43ec, offset, size=4)

        patches.append("move", 0x900c4cd8, offset, size=2984)
        patches.append("add", 0x459c, offset, size=4)

        patches.append("move", 0x900c5880, offset, size=120)
        patches.append("add", 0x4594, offset, size=4)

        # Images Notes:
        #    * In-between images are just zeros.
        #
        # start: 0x900C_58F8   end: 0x900C_D83F    mario sleeping
        # start: 0x900C_D858   end: 0x900D_6C65    mario juggling
        # start: 0x900D_6C78   end: 0x900E_16E2    bowser sleeping
        # start: 0x900E_16F8   end: 0x900E_C301    mario and luigi eating pizza
        # start: 0x900E_C318   end: 0x900F_4D04    minions sleeping
        #          zero_padded_end: 0x900f_4d18
        # Total Image Length: 193_568 bytes
        total_image_length = 193_568
        patches.append("replace", 0x900c58f8, b"\x00" * total_image_length,
                       message="Deleting sleeping images")
        offset -= total_image_length


        patches.append("move", 0x900f4d18, offset, size=2880)
        patches.append("add", 0x10960, offset, size=4)


        # What is this data?
        # The memcpy to this address is all zero, so i guess its not used?
        #patches.append("move", 0x900f5858, offset, size=34728)
        #patches.append("add", 0x7210, offset, size=4)
        patches.append("replace", 0x900f5858, b"\x00" * 34728)
        offset -= 34728


        # TODO: Only the two save blocks remain here


        # The last 2 4096 byte blocks represent something in settings.
        # Each only contains 0x50 bytes of data.
        offset = _round_down_page(offset)

        patches.append("ks_thumb", 0x4856,
                 "ite ne; "
                f"movne.w r4, #{hex(0xff000 + offset)}; "
                f"moveq.w r4, #{hex(0xfe000 + offset)}",
                size=10,
                message="Update NVRAM read addresses"
        )
        patches.append("ks_thumb", 0x48c0,
                 "ite ne; "
                f"movne.w r4, #{hex(0xff000 + offset)}; "
                f"moveq.w r4, #{hex(0xfe000 + offset)}",
                size=10,
                message="Update NVRAM write addresses"
        )

        # Finally, shorten the firmware
        patches.append("add", 0x1_06ec, offset, size=4)
        patches.append("shorten", 0x9000_0000, offset)

    return patches
