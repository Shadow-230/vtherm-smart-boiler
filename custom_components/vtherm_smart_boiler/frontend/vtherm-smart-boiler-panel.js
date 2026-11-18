// node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: f, getOwnPropertySymbols: p, getPrototypeOf: m } = Object, h = globalThis, g = h.trustedTypes, _ = g ? g.emptyScript : "", v = h.reactiveElementPolyfillSupport, y = (e, t) => e, b = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? _ : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, ee = (e, t) => !l(e, t), te = {
	attribute: !0,
	type: String,
	converter: b,
	reflect: !1,
	useDefault: !1,
	hasChanged: ee
};
Symbol.metadata ??= Symbol("metadata"), h.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var x = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = te) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? te;
	}
	static _$Ei() {
		if (this.hasOwnProperty(y("elementProperties"))) return;
		let e = m(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(y("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(y("properties"))) {
			let e = this.properties, t = [...f(e), ...p(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? b : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? b : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? ee)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
x.elementStyles = [], x.shadowRootOptions = { mode: "open" }, x[y("elementProperties")] = /* @__PURE__ */ new Map(), x[y("finalized")] = /* @__PURE__ */ new Map(), v?.({ ReactiveElement: x }), (h.reactiveElementVersions ??= []).push("2.1.2");
// node_modules/lit-html/lit-html.js
var S = globalThis, ne = (e) => e, C = S.trustedTypes, re = C ? C.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, ie = "$lit$", w = `lit$${Math.random().toFixed(9).slice(2)}$`, ae = "?" + w, oe = `<${ae}>`, T = document, E = () => T.createComment(""), D = (e) => e === null || typeof e != "object" && typeof e != "function", se = Array.isArray, ce = (e) => se(e) || typeof e?.[Symbol.iterator] == "function", le = "[ 	\n\f\r]", O = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ue = /-->/g, de = />/g, k = RegExp(`>|${le}(?:([^\\s"'>=/]+)(${le}*=${le}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), fe = /'/g, pe = /"/g, me = /^(?:script|style|textarea|title)$/i, he = (e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}), A = he(1), ge = he(2), j = Symbol.for("lit-noChange"), M = Symbol.for("lit-nothing"), _e = /* @__PURE__ */ new WeakMap(), N = T.createTreeWalker(T, 129);
function ve(e, t) {
	if (!se(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return re === void 0 ? t : re.createHTML(t);
}
var ye = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = O;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === O ? c[1] === "!--" ? o = ue : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = k) : (me.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = k) : o = de : o === k ? c[0] === ">" ? (o = i ?? O, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? k : c[3] === "\"" ? pe : fe) : o === pe || o === fe ? o = k : o === ue || o === de ? o = O : (o = k, i = void 0);
		let d = o === k && e[t + 1].startsWith("/>") ? " " : "";
		a += o === O ? n + oe : l >= 0 ? (r.push(s), n.slice(0, l) + ie + n.slice(l) + w + d) : n + w + (l === -2 ? t : d);
	}
	return [ve(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, P = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = ye(t, n);
		if (this.el = e.createElement(l, r), N.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = N.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(ie)) {
					let t = u[o++], n = i.getAttribute(e).split(w), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? xe : r[1] === "?" ? Se : r[1] === "@" ? Ce : L
					}), i.removeAttribute(e);
				} else e.startsWith(w) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (me.test(i.tagName)) {
					let e = i.textContent.split(w), t = e.length - 1;
					if (t > 0) {
						i.textContent = C ? C.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], E()), N.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], E());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === ae) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(w, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += w.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = T.createElement("template");
		return n.innerHTML = e, n;
	}
};
function F(e, t, n = e, r) {
	if (t === j) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = D(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = F(e, i._$AS(e, t.values), i, r)), t;
}
var be = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? T).importNode(t, !0);
		N.currentNode = r;
		let i = N.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new I(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new we(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = N.nextNode(), a++);
		}
		return N.currentNode = T, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, I = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = M, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = F(this, e, t), D(e) ? e === M || e == null || e === "" ? (this._$AH !== M && this._$AR(), this._$AH = M) : e !== this._$AH && e !== j && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ce(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== M && D(this._$AH) ? this._$AA.nextSibling.data = e : this.T(T.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = P.createElement(ve(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new be(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = _e.get(e.strings);
		return t === void 0 && _e.set(e.strings, t = new P(e)), t;
	}
	k(t) {
		se(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(E()), this.O(E()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = ne(e).nextSibling;
			ne(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, L = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = M, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = M;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = F(this, e, t, 0), a = !D(e) || e !== this._$AH && e !== j, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = F(this, r[n + o], t, o), s === j && (s = this._$AH[o]), a ||= !D(s) || s !== this._$AH[o], s === M ? e = M : e !== M && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === M ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, xe = class extends L {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === M ? void 0 : e;
	}
}, Se = class extends L {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== M);
	}
}, Ce = class extends L {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = F(this, e, t, 0) ?? M) === j) return;
		let n = this._$AH, r = e === M && n !== M || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== M && (n === M || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, we = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		F(this, e);
	}
}, Te = S.litHtmlPolyfillSupport;
Te?.(P, I), (S.litHtmlVersions ??= []).push("3.3.3");
var Ee = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new I(t.insertBefore(E(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, R = globalThis, z = class extends x {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Ee(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return j;
	}
};
z._$litElement$ = !0, z.finalized = !0, R.litElementHydrateSupport?.({ LitElement: z });
var De = R.litElementPolyfillSupport;
De?.({ LitElement: z }), (R.litElementVersions ??= []).push("4.2.2");
// src/localize.ts
var B = {
	en: {
		panel: {
			title: "Boiler",
			loading: "Loading…",
			not_running: "Smart Boiler is not running. Check its entry under Settings → Devices & services.",
			error: "The page could not read Smart Boiler's data: {message}"
		},
		status: {
			monitoring: "Monitoring",
			monitoring_detail: "Control is not set up: the plugin watches the boiler and counts.",
			burner_on: "The burner is on.",
			burner_off: "The burner is off."
		},
		control: {
			label: "Control",
			experimental: "(experimental)",
			hint_on: "Switching off hands the boiler back to its own settings.",
			hint_off: "Switching on asks for confirmation.",
			admin_only: "Only an administrator can change this.",
			unavailable: "Not available now.",
			confirm_off_title: "Switch control off?",
			confirm_off_body: "The plugin stops setting the water temperature and hands the boiler back to its own settings. It keeps watching and counting.",
			confirm_off: "Switch off",
			confirm_on_title: "Switch control on?",
			confirm_on_body: "Control is experimental. The plugin starts setting the boiler's water temperature from the heating curve. You can switch it off at any time, and the boiler returns to its own settings.",
			confirm_on: "Switch on",
			cancel: "Cancel",
			failed: "The switch did not change: {message}"
		},
		tiles: {
			water: "Water — the plugin asks",
			water_confirmed: "confirmed by the boiler",
			water_waiting: "waiting for the boiler to confirm",
			water_none: "nothing asked now",
			flow: "Flow",
			flow_detail: "water leaving the boiler",
			return: "Return",
			return_detail: "water coming back",
			return_condensing: "below 55 °C — the boiler condenses",
			outdoor: "Outdoor",
			outdoor_sensor: "the boiler's sensor",
			outdoor_weather: "from the weather",
			flame: "Flame",
			flame_on: "On",
			flame_off: "Off",
			flame_hot_water: "hot water",
			flame_modulation: "modulation {value} %",
			rooms: "Rooms",
			rooms_value: "{calling} of {total}",
			rooms_detail: "calling for heat"
		},
		schematic: {
			title: "Installation and rooms",
			boiler: "Boiler",
			burning_heating: "burning · heating",
			burning_hot_water: "burning · hot water",
			pause: "pause between burns",
			idle: "idle",
			tank: "Tank",
			hot_water: "hot water",
			cold_water: "cold",
			direct: "straight from the boiler",
			fixed_valve: "thermostatic valve {value} °C",
			other: "other automation",
			other_need: "other automation · needs {value} °C",
			boiler_mixed: "mixed by the boiler",
			rooms: "Who takes heat",
			rooms_hint: "The bar: how hard the room's own controller heats. Outlined: the room calls for heat.",
			takes_heat: "takes heat",
			no_heat: "not calling",
			legend_hot: "hot water",
			legend_mixed: "mixed",
			legend_return: "return",
			legend_idle: "still",
			legend_moving: "white dashes — the water flows · green — a pump or valve at work",
			aria: "Installation: {status}. Rooms taking heat: {rooms}.",
			nobody: "none"
		}
	},
	pl: {
		panel: {
			title: "Kocioł",
			loading: "Wczytywanie…",
			not_running: "Smart Boiler nie działa. Sprawdź jego wpis w Ustawienia → Urządzenia i usługi.",
			error: "Strona nie mogła odczytać danych Smart Boiler: {message}"
		},
		status: {
			monitoring: "Obserwacja",
			monitoring_detail: "Sterowanie nie jest skonfigurowane: wtyczka obserwuje kocioł i liczy.",
			burner_on: "Palnik pali.",
			burner_off: "Palnik nie pali."
		},
		control: {
			label: "Sterowanie",
			experimental: "(eksperymentalne)",
			hint_on: "Wyłączenie oddaje kocioł jego własnym ustawieniom.",
			hint_off: "Włączenie wymaga potwierdzenia.",
			admin_only: "Zmienić to może tylko administrator.",
			unavailable: "Teraz niedostępne.",
			confirm_off_title: "Wyłączyć sterowanie?",
			confirm_off_body: "Wtyczka przestanie ustawiać temperaturę wody i odda kocioł jego własnym ustawieniom. Dalej będzie obserwować i liczyć.",
			confirm_off: "Wyłącz",
			confirm_on_title: "Włączyć sterowanie?",
			confirm_on_body: "Sterowanie jest eksperymentalne. Wtyczka zacznie ustawiać temperaturę wody w kotle według krzywej grzewczej. W każdej chwili możesz je wyłączyć, a kocioł wróci do swoich ustawień.",
			confirm_on: "Włącz",
			cancel: "Anuluj",
			failed: "Przełącznik się nie zmienił: {message}"
		},
		tiles: {
			water: "Woda — prośba wtyczki",
			water_confirmed: "kocioł potwierdził",
			water_waiting: "czeka na potwierdzenie kotła",
			water_none: "teraz bez prośby",
			flow: "Zasilanie",
			flow_detail: "woda wychodząca z kotła",
			return: "Powrót",
			return_detail: "woda wracająca",
			return_condensing: "poniżej 55 °C — kocioł kondensuje",
			outdoor: "Na zewnątrz",
			outdoor_sensor: "czujnik kotła",
			outdoor_weather: "z pogody",
			flame: "Płomień",
			flame_on: "Pali",
			flame_off: "Nie pali",
			flame_hot_water: "ciepła woda",
			flame_modulation: "modulacja {value} %",
			rooms: "Pokoje",
			rooms_value: "{calling} z {total}",
			rooms_detail: "woła o ciepło"
		},
		schematic: {
			title: "Instalacja i pokoje",
			boiler: "Kocioł",
			burning_heating: "pali · ogrzewanie",
			burning_hot_water: "pali · ciepła woda",
			pause: "przerwa między paleniami",
			idle: "stoi",
			tank: "Zasobnik",
			hot_water: "c.w.u.",
			cold_water: "zimna",
			direct: "prosto z kotła",
			fixed_valve: "zawór termostatyczny {value} °C",
			other: "inna automatyka",
			other_need: "inna automatyka · potrzeba {value} °C",
			boiler_mixed: "mieszany przez kocioł",
			rooms: "Kto bierze ciepło",
			rooms_hint: "Pasek — jak mocno grzeje regulator pokoju. Obwódka — pokój woła o ciepło.",
			takes_heat: "bierze ciepło",
			no_heat: "nie woła",
			legend_hot: "gorąca woda",
			legend_mixed: "zmieszana",
			legend_return: "powrót",
			legend_idle: "stoi",
			legend_moving: "białe kreski — woda płynie · zielone — pompa lub zawór pracuje",
			aria: "Instalacja: {status}. Ciepło biorą: {rooms}.",
			nobody: "nikt"
		}
	}
};
function Oe(e) {
	if (!e) return B.en;
	let t = e.toLowerCase();
	return B[t] ?? B[t.split("-")[0]] ?? B.en;
}
function ke(e, t) {
	let n = e;
	for (let e of t.split(".")) {
		if (typeof n != "object") return;
		n = n[e];
	}
	return typeof n == "string" ? n : void 0;
}
function V(e, t, n) {
	let r = ke(Oe(e), t) ?? ke(B.en, t) ?? t;
	return n ? r.replace(/\{(\w+)\}/g, (e, t) => n[t] ?? e) : r;
}
// src/format.ts
var Ae = /* @__PURE__ */ new Set([
	"unknown",
	"unavailable",
	"none",
	""
]);
function H(e) {
	if (e == null || Ae.has(e)) return null;
	let t = Number(e);
	return Number.isFinite(t) ? t : null;
}
function U(e, t, n = 1) {
	if (e == null || !Number.isFinite(e)) return "—";
	try {
		return new Intl.NumberFormat(t, {
			minimumFractionDigits: n,
			maximumFractionDigits: n
		}).format(e);
	} catch {
		return e.toFixed(n);
	}
}
function W(e, t) {
	return e == null ? "—" : `${U(e, t, 1)} °C`;
}
// src/live.ts
var je = 55;
function G(e, t) {
	return t ? e.states[t] : void 0;
}
function K(e, t) {
	return G(e, e.installation.signals[t]);
}
function q(e, t) {
	return G(e, e.installation.entities[t]);
}
function Me(e) {
	return [...new Set(e.circuits.flatMap((e) => e.zones.map((e) => e.entity_id)))];
}
function J(e) {
	let t = q(e, "demand_count")?.attributes.calling_zones;
	return Array.isArray(t) ? t.filter((e) => typeof e == "string") : [];
}
function Ne(e) {
	return K(e, "flame")?.state === "on";
}
function Pe(e) {
	let { t } = e, n = Ne(e), r = q(e, "control_state");
	if (r && r.state !== "unavailable") {
		let t = r.attributes.reasons_text;
		return {
			title: e.stateText(r),
			detail: typeof t == "string" ? t : "",
			flame: n,
			code: r.state
		};
	}
	let i = K(e, "flame") ? t(n ? "status.burner_on" : "status.burner_off") : t("status.monitoring_detail");
	return {
		title: t("status.monitoring"),
		detail: i,
		flame: n,
		code: "monitoring"
	};
}
function Fe(e) {
	let t = e.installation.entities.control, n = G(e, t);
	return !t || !n ? null : {
		entityId: t,
		on: n.state === "on",
		available: n.state !== "unavailable"
	};
}
function Ie(e) {
	let { t, language: n, installation: r } = e, i = [], a = q(e, "control_setpoint");
	if (a) {
		let e = H(String(a.attributes.requested ?? "")), r = H(String(a.attributes.read_back ?? "")), o = e != null && r != null && Math.abs(e - r) < .5;
		i.push({
			key: "water",
			label: t("tiles.water"),
			value: W(e, n),
			detail: t(e == null ? "tiles.water_none" : o ? "tiles.water_confirmed" : "tiles.water_waiting")
		});
	}
	let o = K(e, "flow");
	o && i.push({
		key: "flow",
		label: t("tiles.flow"),
		value: W(H(o.state), n),
		detail: t("tiles.flow_detail")
	});
	let s = K(e, "return");
	if (s) {
		let e = H(s.state), a = r.boiler.condensing && e != null && e < je;
		i.push({
			key: "return",
			label: t("tiles.return"),
			value: W(e, n),
			detail: t(a ? "tiles.return_condensing" : "tiles.return_detail")
		});
	}
	let c = K(e, "outdoor"), l = G(e, r.weather), u = l ? H(String(l.attributes.temperature ?? "")) : null;
	if (c || u != null) {
		let e = c ? H(c.state) : null;
		i.push({
			key: "outdoor",
			label: t("tiles.outdoor"),
			value: W(e ?? u, n),
			detail: t(e == null ? "tiles.outdoor_weather" : "tiles.outdoor_sensor")
		});
	}
	let d = K(e, "flame");
	if (d) {
		let r = d.state === "on", a = H(K(e, "modulation")?.state), o = K(e, "dhw_active")?.state === "on";
		i.push({
			key: "flame",
			label: t("tiles.flame"),
			value: t(r ? "tiles.flame_on" : "tiles.flame_off"),
			detail: r && o ? t("tiles.flame_hot_water") : r && a != null ? t("tiles.flame_modulation", { value: U(a, n, 0) }) : ""
		});
	}
	let f = Me(r);
	return f.length && q(e, "demand_count") && i.push({
		key: "rooms",
		label: t("tiles.rooms"),
		value: t("tiles.rooms_value", {
			calling: String(J(e).filter((e) => f.includes(e)).length),
			total: String(f.length)
		}),
		detail: t("tiles.rooms_detail")
	}), i;
}
function Le(e) {
	return {
		status: Pe(e),
		control: Fe(e),
		tiles: Ie(e)
	};
}
// src/schematic.ts
var Y = {
	x: 0,
	y: 70,
	width: 1e3,
	height: 500
}, Re = 440, ze = 540, X = 150, Z = 470;
function Be(e) {
	switch (e.type) {
		case "single_tank": return "tank";
		case "combi":
		case "combi_tank": return "instant";
		case "single": return "none";
	}
	return e.dhw === "storage" ? "tank" : e.dhw === "combi" ? "instant" : "none";
}
function Ve(e) {
	switch (e.control) {
		case "passive_fixed": return "fixed_valve";
		case "separate": return "other";
		case "through_boiler": return "boiler_mixed";
		default: return "direct";
	}
}
function He(e) {
	return e.zones.some((e) => e.emitter === "underfloor") ? "floor" : "radiator";
}
function Ue(e) {
	return ((t) => e.states[e.installation.signals[t] ?? ""])("dhw_active")?.state === "on" ? "dhw" : e.states[e.installation.entities.boiler_called ?? ""]?.state === "on" || J(e).length > 0 ? "heat" : "idle";
}
function We(e, t, n) {
	return `M${e - n} ${t}a${n} ${n} 0 1 0 ${2 * n} 0a${n} ${n} 0 1 0 ${-2 * n} 0`;
}
function Q(e, t, n) {
	let r = 8.25;
	switch (n) {
		case "left": return `M${e - 11} ${t - r}L${e} ${t}L${e - 11} ${t + r}Z`;
		case "right": return `M${e + 11} ${t - r}L${e} ${t}L${e + 11} ${t + r}Z`;
		case "top": return `M${e - r} ${t - 11}L${e} ${t}L${e + r} ${t - 11}Z`;
		case "bottom": return `M${e - r} ${t + 11}L${e} ${t}L${e + r} ${t + 11}Z`;
	}
}
function Ge() {
	return {
		body: "",
		gray: "",
		blue: "",
		red: "",
		mix: "",
		coilOn: "",
		coilOff: "",
		floorOn: "",
		floorOff: "",
		radOn: "",
		radOff: "",
		flow: "",
		arrRed: "",
		arrBlue: "",
		valveOn: "",
		valveOff: "",
		pumps: "",
		pumpOn: "",
		pumpOff: ""
	};
}
function Ke(e, t, n) {
	let r = Ge(), i = (e, t, n) => {
		r[t] += e, n && (r.flow += e);
	}, a = t === "heat", o = Be(e.boiler), s = o === "tank", c = t === "dhw" && s, l = ze / Math.max(1, e.circuits.length), u = e.circuits.map((e, t) => ({
		id: e.id,
		name: e.name,
		kind: Ve(e),
		emitter: He(e),
		active: a && n.has(e.id),
		cx: Re + l * (t + .5),
		setting: e.fixed_temperature,
		need: e.needed,
		zones: [...new Set(e.zones.map((e) => e.entity_id))]
	})), d = u.length ? u[u.length - 1].cx - 25 : 300, f = u.length ? u[u.length - 1].cx + 35 : 300;
	r.body += "M60 124a14 14 0 0 1 14-14h122a14 14 0 0 1 14 14v222a14 14 0 0 1-14 14h-122a14 14 0 0 1-14-14Z";
	let p = a || c;
	if (i(`M210 ${X}H300`, p ? "red" : "gray", p), i(`M300 ${X}H${d}`, a ? "red" : "gray", a), i(`M${f} ${Z}H300`, a ? "blue" : "gray", a), i(`M300 ${Z}H135V360`, p ? "blue" : "gray", p), s) {
		r.body += "M255 205a45 10 0 0 1 90 0V410a45 10 0 0 1-90 0Z", i("M300 161V228", c ? "red" : "gray", c);
		let e = "M300 228H272V243H328V258H272V273H328V288H272V303H328V318H272V333H328V348H300V412";
		c ? (r.coilOn += e, r.flow += e) : r.coilOff += e, i(`M300 412V${Z}`, c ? "blue" : "gray", c), i("M326 199V178", "red", !1), r.arrRed += "M318 180L326 166L334 180Z", i("M398 392H352", "blue", !1), r.arrBlue += "M354 384L341 392L354 400Z", r[p ? "valveOn" : "valveOff"] += Q(300, X, "left"), r[a ? "valveOn" : "valveOff"] += Q(300, X, "right"), r[c ? "valveOn" : "valveOff"] += Q(300, X, "bottom");
	} else o === "instant" && (i("M60 300H30", "red", t === "dhw"), r.arrRed += "M32 292L18 300L32 308Z", i("M16 330H50", "blue", t === "dhw"), r.arrBlue += "M48 322L62 330L48 338Z");
	for (let e of u) {
		let t = e.cx - 25, n = e.cx + 35, a = e.active, o = e.kind !== "direct";
		if (o) {
			i(`M${t} ${X}V194`, a ? "red" : "gray", a), i(`M${t} 216V290`, a ? "mix" : "gray", a);
			for (let e of [
				"top",
				"bottom",
				"left"
			]) r[a ? "valveOn" : "valveOff"] += Q(t, 205, e);
			i(`M${n} 432H${e.cx - 68}V205H${t - 11}`, a ? "blue" : "gray", a);
		} else i(`M${t} ${X}V290`, a ? "red" : "gray", a);
		if (r.pumps += We(t, 252, 13), r[a ? "pumpOn" : "pumpOff"] += `M${t - 7} 246L${t + 7} 246L${t} 260Z`, e.emitter === "radiator") {
			i(`M${t} 290H${e.cx + 38}`, a ? o ? "mix" : "red" : "gray", a);
			for (let t = 0; t < 6; t++) {
				let n = (e.cx - 41 + t * 14.6).toFixed(1);
				r[a ? "radOn" : "radOff"] += `M${n} 296h10v88h-10Z`;
			}
			i(`M${e.cx - 38} 390H${n}`, a ? "blue" : "gray", a);
		} else {
			let i = `M${t} 290V300H${e.cx + 42}V318H${e.cx - 42}V336H${e.cx + 42}V354H${e.cx - 42}V372H${n}V390`;
			a ? (r.floorOn += i, r.flow += i) : r.floorOff += i;
		}
		i(`M${n} 390V${Z}`, a ? "blue" : "gray", a);
	}
	return {
		paths: r,
		circuits: u,
		hotWater: o
	};
}
function qe(e) {
	let { installation: t, states: n, language: r, t: i } = e, a = Ue(e), o = new Set(J(e)), { paths: s, circuits: c, hotWater: l } = Ke(t, a, new Set(t.circuits.filter((e) => e.zones.some((e) => o.has(e.entity_id))).map((e) => e.id))), u = (e) => n[t.signals[e] ?? ""], d = u("flame")?.state === "on", f = [{
		kind: "inside",
		x: 135,
		y: 132,
		text: i("schematic.boiler")
	}], p = i(d ? a === "dhw" ? "schematic.burning_hot_water" : "schematic.burning_heating" : a === "heat" ? "schematic.pause" : "schematic.idle");
	f.push({
		kind: "inside",
		x: 135,
		y: 262,
		text: p
	});
	let m = H(u("modulation")?.state);
	d && m != null && f.push({
		kind: "inside",
		x: 135,
		y: 284,
		text: i("tiles.flame_modulation", { value: U(m, r, 0) })
	});
	let h = u("flow");
	h && f.push({
		kind: "value",
		x: 252,
		y: 126,
		text: W(H(h.state), r)
	});
	let g = u("return");
	g && f.push({
		kind: "value",
		x: 220,
		y: 492,
		text: W(H(g.state), r)
	});
	let _ = u("pressure");
	if (_) {
		let e = H(_.state);
		f.push({
			kind: "value",
			x: 88,
			y: 390,
			text: e == null ? "—" : `${U(e, r, 1)} bar`
		});
	}
	let v = H(u("outdoor")?.state);
	v != null && (f.push({
		kind: "text",
		x: 925,
		y: 96,
		text: i("tiles.outdoor")
	}), f.push({
		kind: "value",
		x: 925,
		y: 120,
		text: W(v, r)
	})), l === "tank" ? (f.push({
		kind: "text",
		x: 376,
		y: 444,
		text: i("schematic.tank")
	}), f.push({
		kind: "text",
		x: 380,
		y: 170,
		text: i("schematic.hot_water")
	}), f.push({
		kind: "text",
		x: 414,
		y: 372,
		text: i("schematic.cold_water")
	})) : l === "instant" && (f.push({
		kind: "text",
		x: 30,
		y: 282,
		text: i("schematic.hot_water")
	}), f.push({
		kind: "text",
		x: 30,
		y: 348,
		text: i("schematic.cold_water")
	}));
	for (let e of c) {
		f.push({
			kind: "text",
			x: e.cx,
			y: 500,
			text: e.name
		});
		let t = e.kind === "fixed_valve" && e.setting != null ? i("schematic.fixed_valve", { value: U(e.setting, r, 0) }) : e.kind === "other" && e.need != null ? i("schematic.other_need", { value: U(e.need, r, 0) }) : i(`schematic.${e.kind}`);
		f.push({
			kind: "text",
			x: e.cx,
			y: 520,
			text: t
		});
	}
	return {
		paths: s,
		circuits: c,
		hotWater: l,
		mode: a,
		labels: f,
		flame: d
	};
}
function Je(e, t) {
	let { states: n, language: r } = e, i = new Set(J(e));
	return t.map((e) => e.zones.map((e) => {
		let t = n[e]?.attributes ?? {}, a = H(String(t.on_percent ?? "")), o = H(String(t.valve_open_percent ?? "")), s = a == null ? o : a * 100, c = t.friendly_name;
		return {
			entityId: e,
			name: typeof c == "string" && c ? c : e,
			temperature: W(H(String(t.current_temperature ?? "")), r),
			target: W(H(String(t.temperature ?? "")), r),
			demand: s == null ? null : Math.max(0, Math.min(100, Math.round(s))),
			calling: i.has(e)
		};
	}));
}
// src/schematic-card.ts
var Ye = "vtherm-smart-boiler-schematic", Xe = "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z";
function $(e, t, n) {
	return `${((e - t) / n * 100).toFixed(2)}%`;
}
var Ze = class extends z {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 }
		};
	}
	t(e, t) {
		return V(this.hass?.language, e, t);
	}
	inputs() {
		let e = this.hass;
		return !e || !this.installation ? null : {
			installation: this.installation,
			states: e.states,
			language: e.locale?.language ?? e.language,
			t: (e, t) => this.t(e, t),
			stateText: (t) => e.formatEntityState?.(t) ?? t.state
		};
	}
	render() {
		let e = this.inputs();
		if (!e) return M;
		let t = qe(e), n = Je(e, t.circuits), { paths: r } = t, i = t.circuits.length, a = i ? `minmax(0, 44fr) repeat(${i}, minmax(0, ${(54 / i).toFixed(2)}fr)) minmax(0, 2fr)` : "1fr", o = n.flat().filter((e) => e.calling).map((e) => e.name), s = t.labels[1]?.text ?? "", c = `${Y.x} ${Y.y} ${Y.width} ${Y.height}`;
		return A`
      <section class="card">
        <h3>${this.t("schematic.title")}</h3>
        <div class="scroll">
          <div class="inner">
            <div
              class="drawing"
              role="img"
              aria-label=${this.t("schematic.aria", {
			status: s,
			rooms: o.length ? o.join(", ") : this.t("schematic.nobody")
		})}
            >
              <svg viewBox=${c} aria-hidden="true">
                <defs>
                  <linearGradient id="sb-body" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stop-color="#fbfbfa"></stop>
                    <stop offset="1" stop-color="#b9b8b2"></stop>
                  </linearGradient>
                  <linearGradient id="sb-hot" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stop-color="#e34948"></stop>
                    <stop offset="1" stop-color="#2a78d6"></stop>
                  </linearGradient>
                  <linearGradient id="sb-still" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stop-color="#c9c8c2"></stop>
                    <stop offset="1" stop-color="#8f8e88"></stop>
                  </linearGradient>
                </defs>
                ${ge`
                  <path class="body" d=${r.body}></path>
                  <path class="pipe gray" d=${r.gray}></path>
                  <path class="pipe blue" d=${r.blue}></path>
                  <path class="pipe red" d=${r.red}></path>
                  <path class="pipe mix" d=${r.mix}></path>
                  <path class="coil off" d=${r.coilOff}></path>
                  <path class="coil on" d=${r.coilOn}></path>
                  <path class="floor off" d=${r.floorOff}></path>
                  <path class="floor on" d=${r.floorOn}></path>
                  <path class="rad off" d=${r.radOff}></path>
                  <path class="rad on" d=${r.radOn}></path>
                  <path class="flow" d=${r.flow}></path>
                  <path class="arrow red" d=${r.arrRed}></path>
                  <path class="arrow blue" d=${r.arrBlue}></path>
                  <path class="valve off" d=${r.valveOff}></path>
                  <path class="valve on" d=${r.valveOn}></path>
                  <path class="pump" d=${r.pumps}></path>
                  <path class="pump-mark off" d=${r.pumpOff}></path>
                  <path class="pump-mark on" d=${r.pumpOn}></path>
                `}
              </svg>
              <svg
                class="flame ${t.flame ? "lit" : ""}"
                viewBox="0 0 24 24"
                aria-hidden="true"
                style="left: ${$(135, Y.x, Y.width)}; top: ${$(205, Y.y, Y.height)}"
              >
                <path d=${Xe}></path>
              </svg>
              ${t.labels.map((e) => A`<span
                  class=${e.kind}
                  style="left: ${$(e.x, Y.x, Y.width)}; top: ${$(e.y, Y.y, Y.height)}"
                  >${e.text}</span
                >`)}
            </div>
          </div>
        </div>
        ${i ? A`<div class="rooms" style="grid-template-columns: ${a}">
                  <div class="rooms-intro">
                    <div class="strong">${this.t("schematic.rooms")}</div>
                    <div class="muted small">${this.t("schematic.rooms_hint")}</div>
                  </div>
                  ${n.map((e, n) => A`<div class="column">
                      <div class="column-name">${t.circuits[n].name}</div>
                      ${e.map((e) => A`<div class="room ${e.calling ? "calling" : ""}">
                          <div class="room-top">
                            <span class="strong">${e.name}</span>
                            <span class="nums">${e.temperature} <span class="muted">/ ${e.target}</span></span>
                          </div>
                          <div class="room-bar">
                            ${e.demand == null ? M : A`<div class="track">
                                  <div class="fill" style="width: ${e.demand}%"></div>
                                </div>`}
                            <span class=${e.calling ? "takes" : "muted"}
                              >${e.calling ? this.t("schematic.takes_heat") : this.t("schematic.no_heat")}${e.demand == null ? "" : ` · ${e.demand} %`}</span
                            >
                          </div>
                        </div>`)}
                    </div>`)}
                </div>` : M}
        <div class="legend">
          <span><i class="hot"></i>${this.t("schematic.legend_hot")}</span>
          <span><i class="mixed"></i>${this.t("schematic.legend_mixed")}</span>
          <span><i class="cold"></i>${this.t("schematic.legend_return")}</span>
          <span><i class="still"></i>${this.t("schematic.legend_idle")}</span>
          <span>${this.t("schematic.legend_moving")}</span>
        </div>
      </section>
    `;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      container-type: inline-size;
      --sb-hot: #e34948;
      --sb-cold: #2a78d6;
      --sb-mix: #eb6834;
      --sb-still: #a9a8a2;
      --sb-line: #6b6964;
      --sb-pump: #1f9d3a;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 14px;
      box-sizing: border-box;
      min-width: 0;
    }
    h3 {
      margin: 0 0 6px;
      font-size: 16px;
      font-weight: 600;
    }
    .scroll {
      overflow-x: auto;
    }
    .inner {
      min-width: 720px;
    }
    .drawing {
      position: relative;
      width: 100%;
      aspect-ratio: 1000 / 500;
    }
    .drawing > svg:first-child {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }
    .body {
      fill: url(#sb-body);
      stroke: var(--sb-line);
      stroke-width: 1.5;
    }
    .pipe {
      fill: none;
      stroke-width: 7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .pipe.red {
      stroke: var(--sb-hot);
    }
    .pipe.blue {
      stroke: var(--sb-cold);
    }
    .pipe.mix {
      stroke: var(--sb-mix);
    }
    .pipe.gray {
      stroke: var(--sb-still);
    }
    .flow {
      fill: none;
      stroke: rgba(255, 255, 255, 0.9);
      stroke-width: 2.5;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: 3 13;
      animation: flow 0.8s linear infinite;
    }
    @keyframes flow {
      to {
        stroke-dashoffset: -32;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .flow {
        animation: none;
      }
    }
    .coil,
    .floor {
      fill: none;
      stroke-linejoin: round;
      stroke-linecap: round;
    }
    .coil {
      stroke-width: 4;
    }
    .floor {
      stroke-width: 6;
    }
    .coil.on {
      stroke: var(--sb-hot);
    }
    .floor.on {
      stroke: url(#sb-hot);
    }
    .coil.off,
    .floor.off {
      stroke: var(--sb-still);
    }
    .rad {
      stroke: var(--sb-line);
      stroke-width: 1;
    }
    .rad.on {
      fill: url(#sb-hot);
    }
    .rad.off {
      fill: url(#sb-still);
    }
    .arrow.red {
      fill: var(--sb-hot);
    }
    .arrow.blue {
      fill: var(--sb-cold);
    }
    .valve {
      stroke: var(--sb-line);
      stroke-width: 1;
    }
    .valve.on {
      fill: var(--sb-pump);
    }
    .valve.off {
      fill: #d6d5cf;
    }
    .pump {
      fill: #f4f4f2;
      stroke: var(--sb-line);
      stroke-width: 1.5;
    }
    .pump-mark.on {
      fill: var(--sb-pump);
    }
    .pump-mark.off {
      fill: var(--sb-still);
    }
    .flame {
      position: absolute;
      width: 40px;
      height: 40px;
      transform: translate(-50%, -50%);
      fill: none;
      stroke: var(--sb-still);
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
      pointer-events: none;
    }
    .flame.lit {
      stroke: var(--state-climate-heat-color, #ff8100);
    }
    .text,
    .value {
      position: absolute;
      transform: translate(-50%, -50%);
      white-space: nowrap;
      pointer-events: none;
    }
    .text,
    .inside {
      position: absolute;
      transform: translate(-50%, -50%);
      white-space: nowrap;
      pointer-events: none;
      font-size: 12px;
    }
    .text {
      color: var(--secondary-text-color);
    }
    .inside {
      color: #3d3c38; /* the boiler's body is light in every theme */
    }
    .value {
      background: #1d1d1c;
      color: #fff;
      font-weight: 600;
      font-size: 13px;
      padding: 3px 8px;
      border-radius: 6px;
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.18);
      font-variant-numeric: tabular-nums;
    }
    .rooms {
      display: grid;
      gap: 10px;
      margin-top: 4px;
    }
    .rooms-intro {
      padding: 4px 8px 0 4px;
    }
    .column {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .column-name {
      display: none;
      font-size: 13px;
      font-weight: 600;
      color: var(--secondary-text-color);
    }
    /* Narrower than the drawing: the drawing scrolls; the rooms stack, each circuit named. */
    @container (max-width: 760px) {
      .rooms {
        grid-template-columns: minmax(0, 1fr) !important;
      }
      .column-name {
        display: block;
        margin-top: 6px;
      }
    }
    .room {
      background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 10px;
      padding: 8px 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .room.calling {
      border-color: var(--sb-mix);
      box-shadow: inset 0 0 0 0.5px var(--sb-mix);
    }
    .room-top {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 6px;
      font-size: 13px;
    }
    .nums {
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .room-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
    }
    .track {
      height: 6px;
      border-radius: 3px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.08));
      overflow: hidden;
      flex: 1;
    }
    .fill {
      height: 6px;
      border-radius: 3px;
      background: var(--primary-color);
    }
    .takes {
      color: var(--sb-mix);
    }
    .strong {
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
      font-weight: 500;
    }
    .small {
      font-size: 12px;
      font-weight: 400;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
      padding: 12px 2px 0;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend i {
      display: inline-block;
      width: 16px;
      height: 5px;
      border-radius: 3px;
    }
    .legend .hot {
      background: var(--sb-hot);
    }
    .legend .mixed {
      background: var(--sb-mix);
    }
    .legend .cold {
      background: var(--sb-cold);
    }
    .legend .still {
      background: var(--sb-still);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-schematic") || customElements.define(Ye, Ze);
// src/overview.ts
var Qe = "vtherm-smart-boiler-overview", $e = "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z", et = class extends z {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			confirming: { state: !0 },
			error: { state: !0 }
		};
	}
	constructor() {
		super(), this.confirming = !1, this.error = "";
	}
	t(e, t) {
		return V(this.hass?.language, e, t);
	}
	view() {
		let e = this.hass;
		return !e || !this.installation ? null : Le({
			installation: this.installation,
			states: e.states,
			language: e.locale?.language ?? e.language,
			t: (e, t) => this.t(e, t),
			stateText: (t) => e.formatEntityState?.(t) ?? t.state
		});
	}
	get isAdmin() {
		return this.hass?.user?.is_admin === !0;
	}
	ask() {
		this.error = "", this.confirming = !0;
	}
	async decide(e, t) {
		this.confirming = !1;
		let n = t.control;
		if (e && n && this.hass) try {
			await this.hass.callService("switch", n.on ? "turn_off" : "turn_on", { entity_id: n.entityId });
		} catch (e) {
			let t = e instanceof Error ? e.message : String(e?.message ?? e);
			this.error = this.t("control.failed", { message: t });
		}
	}
	updated() {
		let e = this.renderRoot.querySelector("dialog");
		e && (this.confirming && !e.open && e.showModal(), !this.confirming && e.open && e.close());
	}
	render() {
		let e = this.view();
		if (!e) return M;
		let { status: t, control: n, tiles: r } = e, i = n !== null && n.available && this.isAdmin, a = n ? n.available ? this.isAdmin ? n.on ? this.t("control.hint_on") : this.t("control.hint_off") : this.t("control.admin_only") : this.t("control.unavailable") : "";
		return A`
      <section class="card hero">
        <div class="status">
          <div class="flame ${t.flame ? "lit" : ""}" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d=${$e}></path></svg>
          </div>
          <div class="words">
            <h2>${t.title}</h2>
            ${t.detail ? A`<p>${t.detail}</p>` : M}
          </div>
        </div>
        ${n ? A`<div class="control">
              <div class="label">
                <div>${this.t("control.label")} <span class="muted">${this.t("control.experimental")}</span></div>
                <div class="muted small">${a}</div>
              </div>
              <button
                class="switch ${n.on ? "on" : ""}"
                role="switch"
                aria-checked=${n.on ? "true" : "false"}
                aria-label=${this.t("control.label")}
                ?disabled=${!i}
                @click=${() => this.ask()}
              >
                <span class="knob"></span>
              </button>
            </div>` : M}
        ${this.error ? A`<p class="error" role="alert">${this.error}</p>` : M}
      </section>

      ${r.length ? A`<section class="tiles" aria-label=${this.t("panel.title")}>
            ${r.map((e) => A`<div class="card tile">
                <div class="tile-label">${e.label}</div>
                <div class="tile-value">${e.value}</div>
                <div class="muted small">${e.detail}</div>
              </div>`)}
          </section>` : M}

      <vtherm-smart-boiler-schematic
        .hass=${this.hass}
        .installation=${this.installation}
      ></vtherm-smart-boiler-schematic>

      ${n ? A`<dialog aria-labelledby="confirm-title" @cancel=${() => this.confirming = !1}>
            <h2 id="confirm-title">
              ${n.on ? this.t("control.confirm_off_title") : this.t("control.confirm_on_title")}
            </h2>
            <p>${n.on ? this.t("control.confirm_off_body") : this.t("control.confirm_on_body")}</p>
            <div class="actions">
              <button class="text" @click=${() => this.decide(!1, e)}>${this.t("control.cancel")}</button>
              <button class="primary" @click=${() => this.decide(!0, e)}>
                ${n.on ? this.t("control.confirm_off") : this.t("control.confirm_on")}
              </button>
            </div>
          </dialog>` : M}
    `;
	}
	static {
		this.styles = o`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
      min-width: 0;
    }
    .hero {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 16px 24px;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 16px;
      flex: 999 1 420px;
      min-width: 0;
    }
    .flame {
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
      display: flex;
      align-items: center;
      justify-content: center;
      flex: none;
      color: var(--disabled-text-color, #9e9e9e);
    }
    .flame.lit {
      color: var(--state-climate-heat-color, #ff8100);
    }
    .flame svg {
      width: 30px;
      height: 30px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    h2 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
    .words p {
      margin: 4px 0 0;
      color: var(--secondary-text-color);
    }
    .control {
      display: flex;
      align-items: center;
      gap: 14px;
      flex: 1 1 340px;
      justify-content: flex-end;
      text-align: right;
    }
    .label > div:first-child {
      white-space: nowrap;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .switch {
      appearance: none;
      border: 0;
      padding: 0;
      width: 52px;
      height: 32px;
      border-radius: 16px;
      background: var(--disabled-color, #bdbdbd);
      position: relative;
      cursor: pointer;
      flex: none;
    }
    .switch.on {
      background: var(--primary-color);
    }
    .switch:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    .switch:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 3px;
    }
    .knob {
      position: absolute;
      top: 4px;
      left: 4px;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
      transition: left 0.15s;
    }
    .switch.on .knob {
      left: 24px;
    }
    .error {
      flex-basis: 100%;
      margin: 0;
      color: var(--error-color, #db4437);
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .tile-label {
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .tile-value {
      font-size: 26px;
      font-weight: 600;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    dialog {
      border: 0;
      border-radius: var(--ha-dialog-border-radius, 16px);
      padding: 24px;
      max-width: 440px;
      width: calc(100% - 32px);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.45);
    }
    dialog h2 {
      font-size: 20px;
      margin-bottom: 8px;
    }
    dialog p {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 20px;
    }
    .actions button {
      appearance: none;
      border: 0;
      border-radius: 10px;
      min-height: 40px;
      padding: 0 16px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    .actions .text {
      background: transparent;
      color: var(--primary-color);
    }
    .actions .primary {
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-overview") || customElements.define(Qe, et);
// src/panel.ts
var tt = "vtherm-smart-boiler-panel", nt = class extends z {
	static {
		this.properties = {
			hass: { attribute: !1 },
			narrow: { type: Boolean },
			panel: { attribute: !1 },
			load: { state: !0 }
		};
	}
	constructor() {
		super(), this.requested = !1, this.narrow = !1, this.load = { kind: "loading" };
	}
	t(e, t) {
		return V(this.hass?.language, e, t);
	}
	willUpdate() {
		this.hass && !this.requested && (this.requested = !0, this.fetchInstallation());
	}
	async fetchInstallation() {
		if (this.hass) {
			this.load = { kind: "loading" };
			try {
				let e = await this.hass.callWS({ type: "vtherm_smart_boiler/installation" });
				this.load = {
					kind: "ready",
					installation: e
				};
			} catch (e) {
				let t = e?.code, n = e?.message;
				this.load = t === "not_running" ? { kind: "not_running" } : {
					kind: "error",
					message: typeof n == "string" ? n : String(e)
				};
			}
		}
	}
	body() {
		switch (this.load.kind) {
			case "loading": return A`<p class="note">${this.t("panel.loading")}</p>`;
			case "not_running": return A`<p class="note">${this.t("panel.not_running")}</p>`;
			case "error": return A`<p class="note error" role="alert">
          ${this.t("panel.error", { message: this.load.message })}
        </p>`;
			case "ready": return A`<vtherm-smart-boiler-overview
          .hass=${this.hass}
          .installation=${this.load.installation}
        ></vtherm-smart-boiler-overview>`;
		}
	}
	render() {
		return A`
      <header class="toolbar">
        ${this.narrow ? A`<ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>` : M}
        <h1>${this.t("panel.title")}</h1>
      </header>
      <main>${this.body()}</main>
    `;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      min-height: 100%;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: var(--header-height, 56px);
      padding: 0 16px;
      box-sizing: border-box;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, var(--text-primary-color));
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 400;
    }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 16px;
    }
    .note {
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color, #db4437);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-panel") || customElements.define(tt, nt);
export { tt as PANEL_TAG, nt as SmartBoilerPanel };
