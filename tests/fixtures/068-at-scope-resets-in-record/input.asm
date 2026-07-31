* fixture: inside a data RECORD, an ordinary (non-@) FIELD label resets @-local
* scope, so an `@label` reused under successive field labels stays DISTINCT.
* discovered: StyleWriter dialogdata.a DialogDataRec reuses @TitleStart/@TitleEnd
* under heightTitleItem/pagesTitleItem/.../copiesTitleItem, each with
* `dc.l @TitleStart` + `dc.w @TitleEnd-@TitleStart`. gsasm did NOT reset @-scope
* at labels inside a record, so all four @TitleStart collapsed to one scope and
* the TitleRef/TextSize pairs bound to the wrong string. Here itemA's length
* must be 2 ('AA') and itemB's must be 3 ('BBB'); pre-fix both bound to one @s.
Rec	record	export
	export	itemA
itemA	dc.l	@s			;TitleRef -> 'AA'
	dc.w	@e-@s			;TextSize -> 2
@s	dc.b	'AA'
@e
	export	itemB
itemB	dc.l	@s			;TitleRef -> 'BBB'
	dc.w	@e-@s			;TextSize -> 3
@s	dc.b	'BBB'
@e
	endr
	end
