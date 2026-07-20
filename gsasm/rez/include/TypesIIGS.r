/*
 * Types.r — original, clean-room Apple IIgs Rez type templates for gsrez.
 *
 * Part of gsasm (MIT).  NOT Apple's TypesIIGS.r: every template here was
 * derived from (resource-body values -> golden compiled bytes) oracle pairs
 * over the byte-exact System 6.0.1 Rez corpus (work/rez_types_diag.py, see
 * docs/REZ_TYPES_PLAN.md), corroborated against the published resource
 * formats (Apple IIgs Toolbox Reference Vol 3; GS/OS TechNotes).  Template
 * names, type numbers, switch-case labels, and named values are the
 * corpus-dictated compatibility surface; everything else is original.
 *
 * Coverage policy: only templates exercised by a byte-exact corpus target
 * are defined (house rule: no byte oracle, no claim).  The remaining
 * Apple-defined resource types gain templates when a validated target uses
 * them.
 */

/* Resource type numbers (Toolbox Ref Vol 3; used both as the `resource`
 * type selector and as type constants in bodies / read statements). */
#define rIcon               0x8001
#define rControlList        0x8003
#define rControlTemplate    0x8004
#define rPString            0x8006
#define rMenuBar            0x8008
#define rMenu               0x8009
#define rMenuItem           0x800A
#define rTextForLETextBox2  0x800B
#define rCtlDefProc         0x800C
#define rWindParam1         0x800E
#define rWindColor          0x8010
#define rToolStartup        0x8013
#define rAlertString        0x8015
#define rText               0x8016
#define rCodeResource       0x8017
#define rCDEVCode           0x8018
#define rCDEVFlags          0x8019
#define rTwoRects           0x801A
#define rListRef            0x801C
#define rCString            0x801D
#define rErrorString        0x8020
#define rVersion            0x8029
#define rComment            0x802A
#define rBundle             0x802B
#define rFinderPath         0x802C
#define rTaggedStrings      0x802E
#define rRectList           0xC001

/* Control/alert convenience constants used by CDEV sources (values via
 * the token oracle over the 19 CtlPanel .r sources). */
#define ctlVisible           0x0000
#define ctlInvis             0x0080
#define CtlInactive          0xFF00
#define DefaultButton        1
#define ResourceToResource   9
#define refIsPtr             0
#define refIsHandle          1
#define refIsResource        2
#define singlePtr            0
#define FctlProcNotPtr       0x1000
#define fType2PopUp          0x0040
#define fSubTextIsPascal     0x0001
#define fSubstituteText      0x0002
#define fBlastText           0x0004
#define fCtlTie              0x0008
#define fAlert               0x2000
#define fCtlIsMultiPart      0x0400
#define fCtlTellAboutSize    0x0800
#define fCtlWantEvents       0x2000
#define fCtlWantsEvents      0x2000
#define fCtlCanBeTarget      0x4000

/* --- Plain string resources ------------------------------------------- */
/* Raw text, no length prefix, no implicit terminator (rErrorString bodies
 * write their trailing NUL explicitly as \0x00 — oracle: 90 instances). */

/* LETextBox2 embedded formatting codes (Toolbox Ref Vol 3, LineEdit
 * LETextBox2: $01 + 'J'/'S' + a 2-byte parameter selects justification /
 * style; names+values via the token oracle, byte-proven by Teach's
 * rAlertString bodies). */
#define TBEndOfLine       "\n"
#define TBStylePlain      "\$01S\$00\$00"
#define TBStyleOutline    "\$01S\$08\$00"
#define TBCenterJust      "\$01J\$01\$00"

type rPString {            /* length-byte Pascal string (oracle: 10) */
    pstring;
};

type rTextForLETextBox2 {  /* LETextBox2 text with embedded *n / font codes */
    string;
};

type rAlertString {        /* AlertWindow template string */
    string;
};

type rErrorString {        /* SysBeep2/error text, explicit \0x00 tail */
    string;
};

type rComment {            /* free-text comment */
    string;
};

type rText {               /* plain text (TextEdit/help bodies) */
    string;
};

type rCString {            /* C string: text plus implicit trailing NUL */
    cstring;
};

/* --- QuickDraw icon ---------------------------------------------------- */
/* Header of four little-endian words (iconType, iconSize, iconHeight,
 * iconWidth) then the packed 4-bit-per-pixel image and mask hex data.
 * iconSize is NOT body-supplied: it is the byte length of the image data,
 * computed from the label span.  Oracle: 12 instances, 8 + iconSize*2. */

type rIcon {
    integer;                              /* iconType ($8000 color)      */
    integer = (iconMask - iconImage) / 8; /* iconSize = image byte count */
    integer;                              /* iconHeight (pixels)         */
    integer;                              /* iconWidth  (pixels)         */
  iconImage:
    hex string;                           /* image, iconSize bytes       */
  iconMask:
    hex string;                           /* mask, same size             */
};

/* --- Window Manager ----------------------------------------------------- */

/* NewWindow wFrameBits (Toolbox Ref Vol 2; values via the token oracle,
 * byte-proven by Teach's rWindParam1 bodies). */
#define fVis              0x0020
#define fMove             0x0080
#define fZoom             0x0100
#define fClose            0x4000
#define fTitle            0x8000

type rWindColor {          /* NewWindow2 color table: 5 LE words */
    integer;               /* frameColor  */
    integer;               /* titleColor  */
    integer;               /* tBarColor   */
    integer;               /* growColor   */
    integer;               /* infoColor   */
};

/* NewWindow2 paramList (Toolbox Ref Vol 3 / Window Mgr).  The leading
 * paramLength (80) and the 12 reserved bytes after wInfoHeight are
 * template-supplied; the body provides the other 16 values.  Oracle: the
 * wPlane `infront` = $FFFFFFFF and tail layout proven by 3 instances. */

type rWindParam1 {
    integer = 80;          /* paramLength                                 */
    integer;               /* wFrameBits                                  */
    longint;               /* wTitle ref                                  */
    longint;               /* wRefCon                                     */
    rect;                  /* wZoom                                       */
    longint;               /* wColor table ref                            */
    point;                 /* wYOrigin / wXOrigin                         */
    point;                 /* wDataH / wDataW                             */
    point;                 /* wMaxH / wMaxW                               */
    point;                 /* wScrollVer / wScrollHor                     */
    point;                 /* wPageVer / wPageHor                         */
    longint;               /* wInfoRefCon                                 */
    integer;               /* wInfoHeight                                 */
    fill byte[12];         /* wFrameDefProc/wInfoDefProc/wContDefProc     */
    rect;                  /* wPosition                                   */
    longint behind = 0,    /* wPlane (behind: doc-derived, no oracle yet) */
            infront = 0xFFFFFFFF;
    longint;               /* wStorage / control-list ref                 */
    integer;               /* wInVerb (rControlList descriptor)           */
};

/* --- Menu Manager ------------------------------------------------------- */
/* rMenu / rMenuItem mirror the InsertMenu template stream (Toolbox Ref
 * Vol 3).  The leading version word is 0 and the rMenu item-reference list
 * carries a terminating zero long, both template-supplied.  (In Apple's
 * include the terminator is conditional on RezIIGS, which the gsrez
 * pipeline always defines; this include targets that configuration.) */

/* Menu Manager reference/flag constants (Toolbox Ref Vol 3, NewMenu2 /
 * InsertMItem2 refType and flag words; values via the token oracle). */
#define NIL               0
#define RefIsResource     2        /* refType: reference is a resource ID  */
#define ItemRefShift      0x1000   /* itemFlag: item-ref type field shift  */
#define ItemTitleRefShift 0x4000   /* itemFlag: title-ref type field shift */
#define MenuTitleRefShift 0x4000   /* menuFlag: title-ref type field shift */
#define fXOR              0x0020   /* itemFlag: XOR highlighting           */
#define fAllowCache       0x0008   /* menuFlag: allow menu caching         */
#define rmAllowCache      0x0008   /* (Teach spelling)                     */
#define rmDisabled        0x0080   /* menuFlag: menu disabled              */
#define rMIBold           0x0001   /* menu-item itemFlag: bold style       */
#define rMIItalic         0x0002   /* menu-item itemFlag: italic style     */
#define rMIUnderline      0x0004   /* menu-item itemFlag: underline style  */
#define rMIOutline        0x0800   /* menu-item itemFlag: outline style    */
#define rMIShadow         0x1000   /* menu-item itemFlag: shadow style     */

type rMenuBar {            /* SetMenuBar list: rMenu refs.  The $8000 word
                              and the zero-long terminator are template-
                              supplied (terminator per the same RezIIGS
                              configuration as rMenu/rControlList; oracle:
                              Teach's 6-menu bar, 32 bytes).              */
    integer = 0;           /* version                                     */
    integer = 0x8000;      /* refs-are-resource-IDs flag                  */
    array {
        longint;           /* rMenu refs                                  */
    };
    longint = 0;           /* list terminator                             */
};

type rMenu {
    integer = 0;           /* version                                     */
    integer;               /* menuID                                      */
    integer;               /* menuFlag                                    */
    longint;               /* menu title ref                              */
    array {
        longint;           /* rMenuItem refs                              */
    };
    longint = 0;           /* item-list terminator                        */
};

type rMenuItem {
    integer = 0;           /* version                                     */
    integer;               /* itemID                                      */
    char;                  /* itemChar                                    */
    char;                  /* itemAltChar                                 */
    integer;               /* itemCheck                                   */
    integer;               /* itemFlag                                    */
    longint;               /* item title ref                              */
};

/* --- Control Manager ---------------------------------------------------- */

type rControlList {        /* NewControl2 list: rControlTemplate refs */
    array {
        longint;
    };
    longint = 0;           /* list terminator                             */
};

/* NewControl2 single-control template (Toolbox Ref Vol 3, ch.28 "Control
 * Manager Update").  Byte layout: pCount word, control ID long, rect, then
 * the per-defproc parameter block.  pCount = 3 fixed params + however many
 * of the optional params the body supplies (partial fill, oracle: pCount
 * 8/9/10 across 21 instances).  The procRef long doubles as the case
 * discriminator: standard defprocs use $8n000000 codes; iconButtonControl
 * uses the $07FF0001 defproc resource reference convention.  Only the
 * corpus-exercised cases are defined (coverage policy above). */

type rControlTemplate {
    integer = 3 + $$optionalCount(ctlParams);   /* pCount                 */
    unsigned longint;                           /* control ID             */
    rect;                                       /* control rect           */
    switch {
        case simpleButtonControl:
            key unsigned hex longint = 0x80000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* title ref              */
                longint;                        /* color table ref        */
                array {                         /* key equivalent         */
                    char;                       /*   keyChar              */
                    char;                       /*   keyAltChar           */
                    integer;                    /*   keyModifiers         */
                    integer;                    /*   keyCareBits          */
                };
            };
        case radioControl:
            key unsigned hex longint = 0x84000000;
            optional ctlParams {
                integer;                        /* flags (family in low)  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* title ref              */
                integer;                        /* initial value          */
                longint;                        /* color table ref        */
                array {                         /* key equivalent         */
                    char;
                    char;
                    integer;
                    integer;
                };
            };
        case checkControl:
            key unsigned hex longint = 0x82000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* title ref              */
                integer;                        /* initial value          */
                longint;                        /* color table ref        */
                array {                         /* key equivalent         */
                    char;
                    char;
                    integer;
                    integer;
                };
            };
        case scrollControl:
            key unsigned hex longint = 0x86000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* max size               */
                integer;                        /* view size              */
                integer;                        /* initial value          */
                longint;                        /* color table ref        */
            };
        case popUpControl:
            key unsigned hex longint = 0x87000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* title width            */
                longint;                        /* menu ref               */
                integer;                        /* initial value          */
                longint;                        /* color table ref        */
            };
        case statTextControl:
            key unsigned hex longint = 0x81000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* text ref               */
                integer;                        /* text size              */
                integer;                        /* justification          */
            };
        case editLineControl:
            key unsigned hex longint = 0x83000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* max text length        */
                longint;                        /* default text ref       */
                integer;                        /* password char          */
            };
        case listControl:
            key unsigned hex longint = 0x89000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* list size              */
                integer;                        /* list view              */
                integer;                        /* list type              */
                integer;                        /* list start             */
                longint = 0;                    /* list draw routine      */
                integer;                        /* member height          */
                integer;                        /* member size            */
                longint;                        /* list ref               */
                longint;                        /* color table ref        */
            };
        case rectangleControl:
            key unsigned hex longint = 0x87FF0003;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* pen height             */
                integer;                        /* pen width              */
                hex string;                     /* pen mask               */
                hex string;                     /* pen pattern            */
            };
        case iconButtonControl:
            key unsigned hex longint = 0x07FF0001;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* icon ref               */
                longint;                        /* title ref              */
                longint;                        /* color table ref        */
                integer;                        /* display mode           */
                array {                         /* key equivalent         */
                    char;
                    char;
                    integer;
                    integer;
                };
            };
        case editTextControl:
            key unsigned hex longint = 0x85000000;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                longint;                        /* textFlags              */
                rect;                           /* indent rect            */
                longint;                        /* vertical bar ref       */
                integer;                        /* vertical amount        */
                longint;                        /* horizontal bar ref     */
                integer;                        /* horizontal amount      */
                longint;                        /* style ref              */
                integer;                        /* text descriptor        */
                longint;                        /* text ref               */
                longint;                        /* text length            */
                longint;                        /* max chars              */
                longint;                        /* max lines              */
                integer;                        /* max chars per line     */
                integer;                        /* max height             */
                longint;                        /* color table ref        */
                integer;                        /* draw mode              */
                longint;                        /* filter proc ptr        */
            };
        case thermometerControl:
            key unsigned hex longint = 0x87FF0002;
            optional ctlParams {
                integer;                        /* flags                  */
                integer;                        /* moreFlags              */
                longint;                        /* refCon                 */
                integer;                        /* value                  */
                integer;                        /* scale                  */
            };
    };
};

/* --- Version ------------------------------------------------------------ */
/* rVersion (Toolbox Ref Vol 3): a 4-byte version long (stored little-
 * endian, hence the ReverseBytes group over the big-endian field order),
 * a country word, then two Pascal strings (name, more info).  Stage codes:
 * release = $A0 oracle-proven; the earlier stages are doc-derived.
 * Country list: only the corpus-exercised code is defined (coverage
 * policy). */

type rVersion {
    ReverseBytes {
        hex byte;                               /* major (BCD)            */
        hex bitstring[4];                       /* minor                  */
        hex bitstring[4];                       /* bug fix                */
        hex byte development = 0x20,            /* release stage          */
                 alpha       = 0x40,
                 beta        = 0x60,
                 final       = 0x80,
                 release     = 0xA0;
        hex byte;                               /* non-release number     */
    };
    integer verUS = 0;                          /* country code           */
    pstring;                                    /* product name           */
    pstring;                                    /* more info              */
};

/* --- Control Panel devices (CDEVs) -------------------------------------- */
/* rCDEVFlags (Toolbox Ref Vol 3 / Control Panel chapter): the CDEV's
 * capability flag word, four capability bytes, its data rectangle, and
 * three FIXED-CAPACITY Pascal strings (name 15, author 32, version 8 —
 * storage is capacity+1, zero-padded; settled against the General CDEV
 * golden fork).  The rCDEVCode resource is a `read` of the CDEV's linked
 * code, so it needs no template.  Flag-bit values via the token oracle. */
#define wantMachine       0x0001
#define wantBoot          0x0002
#define wantInit          0x0008
#define wantClose         0x0010
#define wantEvents        0x0020
#define wantCreate        0x0040
#define wantAbout         0x0080
#define wantRect          0x0100
#define wantHit           0x0200
#define wantRun           0x0400
#define wantEdit          0x0800
#define updateSSfromBRAM  0x4000

type rCDEVFlags {
    integer;               /* capability flags                            */
    byte;                  /* enabled                                     */
    byte;                  /* version                                     */
    byte;                  /* machine                                     */
    byte;                  /* system                                      */
    rect;                  /* data rectangle                              */
    pstring[15];           /* name    (16-byte field)                     */
    pstring[32];           /* author  (33-byte field — golden width)      */
    pstring[8];            /* version ( 9-byte field — golden width)      */
};

type rTwoRects {           /* window position pair: 320- and 640-mode rects */
    rect;
    rect;
};

type rTaggedStrings {      /* Sound CDEV: leading pair count, then
                              (tag word, pstring) pairs in body order */
    integer = $$Countof(tags);
    wide array tags {
        integer;           /* tag                                         */
        pstring;           /* string                                      */
    };
};

type rListRef {            /* List Manager member list.  Only the EMPTY
                              list is oracle-proven (AppleShare ZoneList,
                              0 golden bytes); member shape is doc-derived. */
    array {
        pstring;
    };
};

/* --- Tool startup ------------------------------------------------------- */
/* rToolStartup (Toolbox Ref Vol 3, StartUpTools): flags, video mode, then
 * a resFileID word and dPageHandle long that the Tool Locator fills in at
 * run time (stored as zeros), a tool count, and (toolNum, minVersion)
 * pairs.  All words little-endian; settled against the Finder golden
 * instance (68 bytes, 14 tools). */

type rToolStartup {
    integer = 0;           /* flags                                       */
    hex integer;           /* video mode                                  */
    integer = 0;           /* resFileID   (filled in at run time)         */
    longint = 0;           /* dPageHandle (filled in at run time)         */
    integer = $$Countof(Tools);
    array Tools {
        integer;           /* tool set number                             */
        hex integer;       /* minimum version                             */
    };
};

/* --- Finder ------------------------------------------------------------- */
/* rRectList (System 6.0 Finder: default window positions et al.): a
 * count word then 8-byte QuickDraw rects.  Oracle: the Finder instance
 * (114 bytes = 2 + 14 rects). */

type rRectList {
    integer = $$Countof(Rects);
    array Rects {
        rect;
    };
};

/* rBundle (System 6.0 Finder icon matching; Finder chapter of the System 6
 * docs).  Compiled shape settled against the Finder golden instance (3623
 * bytes, 54 OneDocs): an 18-byte header (version, byte offset of the doc
 * count, the Finder rIcon ID, this rBundle's ID, a reserved long, count),
 * then per OneDoc a size word (self-inclusive), the byte offset of the
 * match-flags long within the doc, the launch element count, the launch
 * group (flag word, 8-byte path/big-icon/small-icon refs — long ID plus a
 * reserved zero long — and an optional document-name pstring; the small
 * ref and the name may be omitted), the match-flags long, and twelve match
 * sections.  Each section is a two-armed switch: `empty` stores a zero
 * key word; a match case stores its 1-based section number as the key
 * word, then its payload.  matchFlags bit n-1 announces section n.  Only
 * the corpus-exercised cases are defined (coverage policy): sections
 * 4/5/6/8/11/12 (create date, mod date, local access, extended, option
 * list, EOF) appear only as `empty` in the oracle. */

/* Launch flag word bits (values from the golden launch words $11/$31/$F1
 * against the source's symbolic combinations). */
#define DontLaunch        0x0000
#define LaunchThis        0x0001
#define reads             0x0010
#define writes            0x0020
#define native            0x0040
#define creator           0x0080

/* matchFlags bits: bit n-1 <-> match section n (golden $41/$03/$05/$0300
 * against the source's symbolic combinations). */
#define FileType          0x0001
#define AuxType           0x0002
#define FileName          0x0004
#define NetworkAccess     0x0040
#define HFSFileType       0x0100
#define HFSCreator        0x0200

type rBundle {
  bundleStart:
    integer = 0;                              /* version                   */
    integer = (docList - bundleStart) / 8;    /* byte offset of doc count  */
    longint;                                  /* Finder rIcon ID           */
    longint;                                  /* this rBundle's ID         */
    longint = 0;                              /* reserved                  */
  docList:
    integer = $$Countof(OneDoc);
    array OneDoc {
      docStart:
        integer = (docEnd[$$ArrayIndex(OneDoc)]
                   - docStart[$$ArrayIndex(OneDoc)]) / 8;
        integer = (matchOff[$$ArrayIndex(OneDoc)]
                   - docStart[$$ArrayIndex(OneDoc)]) / 8;
        integer = $$optionalCount(Launch);
        optional Launch {
            integer;                          /* launch flags              */
            array [1] {                       /* rFinderPath ref           */
                longint;
                longint = 0;
            };
            array [1] {                       /* big rIcon ref             */
                longint;
                longint = 0;
            };
            array [1] {                       /* small rIcon ref           */
                longint;
                longint = 0;
            };
            pstring;                          /* document name             */
        };
      matchOff:
        longint;                              /* matchFlags                */
        switch {                              /* 1: file type              */
            case MatchFileType:
                integer = 1;
                array [1] { integer; };
            case empty:
                integer = 0;
        };
        switch {                              /* 2: aux type               */
            case MatchAuxType:
                integer = 2;
                array [1] { longint; longint; };   /* mask, value          */
            case empty:
                integer = 0;
        };
        switch {                              /* 3: file name              */
            case MatchFileName:
                integer = 3;
                array [1] { pstring; };
            case empty:
                integer = 0;
        };
        switch {                              /* 4: create date            */
            case empty:
                integer = 0;
        };
        switch {                              /* 5: mod date               */
            case empty:
                integer = 0;
        };
        switch {                              /* 6: local access           */
            case empty:
                integer = 0;
        };
        switch {                              /* 7: network access         */
            case MatchNetworkAccess:
                integer = 7;
                array [1] { longint; longint; };   /* mask, value          */
            case empty:
                integer = 0;
        };
        switch {                              /* 8: extended (storage)     */
            case empty:
                integer = 0;
        };
        switch {                              /* 9: HFS file type          */
            case MatchHFSFileType:
                integer = 9;
                array [1] { longint; };
            case empty:
                integer = 0;
        };
        switch {                              /* 10: HFS creator           */
            case MatchHFSCreator:
                integer = 10;
                array [1] { longint; };
            case empty:
                integer = 0;
        };
        switch {                              /* 11: option list           */
            case empty:
                integer = 0;
        };
        switch {                              /* 12: EOF                   */
            case empty:
                integer = 0;
        };
      docEnd:
    };
};

/* rFinderPath (System 6.0 Finder icon matching: launch path): a version
 * word, the byte offset of the pathname within the resource, and a
 * word-length GS/OS pathname.  The array between them is EMPTY in all 5
 * oracle instances (element shape doc-derived, same policy as rListRef). */

type rFinderPath {
    integer = 0;           /* version                                     */
    longint = PathName / 8; /* byte offset of the pathname                */
    array {
        integer;
    };
  PathName:
    wstring;               /* GS/OS pathname                              */
};
