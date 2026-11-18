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
}, x = (e, t) => !l(e, t), ee = {
	attribute: !0,
	type: String,
	converter: b,
	reflect: !1,
	useDefault: !1,
	hasChanged: x
};
Symbol.metadata ??= Symbol("metadata"), h.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var S = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = ee) {
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
		return this.elementProperties.get(e) ?? ee;
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
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? x)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
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
S.elementStyles = [], S.shadowRootOptions = { mode: "open" }, S[y("elementProperties")] = /* @__PURE__ */ new Map(), S[y("finalized")] = /* @__PURE__ */ new Map(), v?.({ ReactiveElement: S }), (h.reactiveElementVersions ??= []).push("2.1.2");
// node_modules/lit-html/lit-html.js
var te = globalThis, ne = (e) => e, C = te.trustedTypes, re = C ? C.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, ie = "$lit$", w = `lit$${Math.random().toFixed(9).slice(2)}$`, ae = "?" + w, oe = `<${ae}>`, T = document, E = () => T.createComment(""), D = (e) => e === null || typeof e != "object" && typeof e != "function", se = Array.isArray, ce = (e) => se(e) || typeof e?.[Symbol.iterator] == "function", le = "[ 	\n\f\r]", O = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ue = /-->/g, de = />/g, k = RegExp(`>|${le}(?:([^\\s"'>=/]+)(${le}*=${le}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), fe = /'/g, pe = /"/g, me = /^(?:script|style|textarea|title)$/i, he = (e) => (t, ...n) => ({
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
}, be = class e {
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
						ctor: r[1] === "." ? Ce : r[1] === "?" ? we : r[1] === "@" ? Te : F
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
function P(e, t, n = e, r) {
	if (t === j) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = D(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = P(e, i._$AS(e, t.values), i, r)), t;
}
var xe = class {
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
				s.type === 2 ? t = new Se(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Ee(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = N.nextNode(), a++);
		}
		return N.currentNode = T, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, Se = class e {
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
		e = P(this, e, t), D(e) ? e === M || e == null || e === "" ? (this._$AH !== M && this._$AR(), this._$AH = M) : e !== this._$AH && e !== j && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ce(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
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
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = be.createElement(ve(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new xe(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = _e.get(e.strings);
		return t === void 0 && _e.set(e.strings, t = new be(e)), t;
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
}, F = class {
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
		if (i === void 0) e = P(this, e, t, 0), a = !D(e) || e !== this._$AH && e !== j, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = P(this, r[n + o], t, o), s === j && (s = this._$AH[o]), a ||= !D(s) || s !== this._$AH[o], s === M ? e = M : e !== M && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === M ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Ce = class extends F {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === M ? void 0 : e;
	}
}, we = class extends F {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== M);
	}
}, Te = class extends F {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = P(this, e, t, 0) ?? M) === j) return;
		let n = this._$AH, r = e === M && n !== M || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== M && (n === M || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Ee = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		P(this, e);
	}
}, De = te.litHtmlPolyfillSupport;
De?.(be, Se), (te.litHtmlVersions ??= []).push("3.3.3");
var Oe = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new Se(t.insertBefore(E(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, ke = globalThis, I = class extends S {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Oe(t, this.renderRoot, this.renderOptions);
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
I._$litElement$ = !0, I.finalized = !0, ke.litElementHydrateSupport?.({ LitElement: I });
var Ae = ke.litElementPolyfillSupport;
Ae?.({ LitElement: I }), (ke.litElementVersions ??= []).push("4.2.2");
// src/localize.ts
var L = {
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
			failed: "The switch did not change: {message}",
			replay: "replay · {time}",
			replay_hint: "A past moment: nothing can be changed."
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
		},
		curve: {
			title: "Heating curve",
			preview: "Preview changes",
			preview_close: "Close the preview",
			where: "Where we are",
			where_detail: "outdoors, as the curve reads it → water · curve's room {room}",
			where_none: "No water decided yet.",
			no_curve: "Control does not set the water here, so there is no curve.",
			not_entered: "The curve is not entered yet: set it in the plugin's settings.",
			legend_now: "where we are",
			legend_days: "the last 7 days",
			legend_saved: "saved",
			legend_draft: "draft",
			axis: "Outdoor temperature (°C) — up: water (°C)",
			highest: "highest {value}",
			lowest: "lowest {value}",
			design_point: "Point at the hardest frost",
			room: "Curve's room temperature",
			room_auto: "Auto · {value}",
			offset: "Offset",
			exponent: "Emitter exponent",
			limits: "Lowest / highest water",
			correction: "Comfort correction",
			correction_on: "on, up to {value} K",
			correction_off: "off",
			preview_hint: "Drag the blue point — the hardest frost — or use the arrow keys; the slider shifts the whole curve.",
			handle: "Point at the hardest frost: {outdoor} outdoors, {water} water. The arrow keys move it.",
			preview_effect: "At {outdoor} outdoors: water {saved} → {draft}.",
			preview_note: "The preview changes nothing in the boiler. To change the curve, use the plugin's settings; saving from this page comes next.",
			reset: "Back to the saved curve",
			loading_error: "The curve could not be read: {message}",
			problem: {
				design_flow_too_low: "The water at the hardest frost must be at least 5 °C above the curve's room temperature.",
				design_flow_above_hard_max: "The water at the hardest frost is above the highest water: the curve would be cut off in frost.",
				design_outdoor_too_warm: "The hardest frost must be at least 10 °C below the curve's room temperature.",
				hard_min_not_below_design_flow: "The lowest water must be below the water at the hardest frost.",
				hard_min_above_max: "The lowest water is above a circuit's or the boiler's highest.",
				invalid_curve: "These values make no curve.",
				out_of_range: "a value is outside what the settings accept.",
				offset_advanced: "the offset is set at the advanced level of the plugin's settings.",
				needs_settings: "the settings need you for this save — open them to finish.",
				other: "the settings refused it ({key})."
			},
			save: "Save",
			save_title: "Save the curve?",
			save_body: "The plugin's settings save it with their own checks and reload once; control goes on with the new curve.",
			save_point: "Point at the hardest frost",
			saving: "Saving…",
			saved: "Saved: the plugin reloads its settings.",
			refused: "Not saved: {reason}",
			open_settings: "Open the plugin's settings",
			admin_only: "Only an administrator can save the curve."
		},
		timeline: {
			title: "The last 24 h",
			hint: "Scroll or play the day back: the tiles, the schematic, the rooms and the curve show that moment.",
			play: "Play the day",
			pause: "Stop",
			now: "Now",
			slider: "Moment of the day",
			legend_requested: "the plugin asks",
			legend_flow: "flow",
			legend_return: "return",
			legend_heat: "burning: heating",
			legend_hot_water: "burning: hot water",
			loading: "Loading the history…",
			no_history: "No history: the recorder keeps none for these entities.",
			error: "The history could not be read: {message}"
		},
		tabs: {
			overview: "Overview",
			burner: "Burner",
			label: "Views of the page",
			use: "Use"
		},
		burner: {
			starts_per_hour: "Starts per hour",
			starts_per_hour_detail: "heating, the last 24 h",
			median_burn: "Typical burn",
			median_burn_detail: "the median heating burn",
			short_burn_share: "Short burns",
			short_burn_share_detail: "heating burns under {value} min",
			burner_hours: "Burner hours",
			burner_hours_detail: "heating, the last 24 h",
			condensing_share: "Condensing",
			condensing_share_detail: "heating burn time with the return below 55 °C",
			timeline: "Burns — the last 24 h",
			heat: "heating",
			dhw: "hot water",
			unknown: "unknown kind",
			burn: "{from}–{to} · {minutes} min · {kind}",
			summary: "{count} burns in the last 24 h: {heat} heating, {dhw} hot water, {unknown} of unknown kind.",
			lengths: "How long the heating burns lasted",
			lengths_hint: "Burns of the last 24 h by length. Short burns wear the boiler and waste gas.",
			short: "{count} short (under {value} min)",
			minutes: "minutes",
			count: "{label} min: {count}",
			as_of: "As the monitor's analysis of {time} sees them.",
			none: "No burns in the last 24 h.",
			no_analysis: "The monitor has not analysed the burns yet.",
			error: "The burns could not be read: {message}"
		},
		use: {
			gas_per_degree_day: "Gas per degree-day",
			gas_per_degree_day_detail: "the last 7 days — measured with a gas meter, else estimated",
			degree_days: "Degree-days",
			degree_days_detail: "the last 7 days, from the heating threshold",
			weeks: "Gas per degree-day — 12 weeks",
			weeks_hint: "How much gas the house needs for each degree of cold. The weather evens out, so the weeks compare. Lower is better.",
			week: "Week of {date}: {value}",
			week_none: "Week of {date}: not known — gas missing on a day, or too mild",
			weeks_none: "No week yet: the daily summaries are filled day by day.",
			change: "Use against yesterday",
			change_hint: "Where the difference came from.",
			total: "{sign}{value} {unit} ({percent})",
			less: "less",
			more: "more",
			weather: "Weather",
			dhw: "Hot water",
			settings: "Settings",
			other: "The rest",
			normal: "within normal day-to-day variation",
			not_judged: "not judged",
			no_report: "No report yet: it needs two days of data.",
			error: "The use could not be read: {message}"
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
			failed: "Przełącznik się nie zmienił: {message}",
			replay: "odtwarzanie · {time}",
			replay_hint: "Chwila z przeszłości: nic nie da się zmienić."
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
		},
		curve: {
			title: "Krzywa grzewcza",
			preview: "Podgląd zmian",
			preview_close: "Zamknij podgląd",
			where: "Gdzie jesteśmy",
			where_detail: "na zewnątrz, tak jak czyta krzywa → woda · pokój krzywej {room}",
			where_none: "Woda nie jest jeszcze ustalona.",
			no_curve: "Sterowanie nie ustawia tu wody, więc nie ma krzywej.",
			not_entered: "Krzywa nie jest jeszcze wpisana: ustaw ją w ustawieniach wtyczki.",
			legend_now: "gdzie jesteśmy",
			legend_days: "ostatnie 7 dni",
			legend_saved: "zapisana",
			legend_draft: "robocza",
			axis: "Temperatura na zewnątrz (°C) — w górę: woda (°C)",
			highest: "najwyższa {value}",
			lowest: "najniższa {value}",
			design_point: "Punkt przy największym mrozie",
			room: "Temperatura pokoju krzywej",
			room_auto: "Auto · {value}",
			offset: "Przesunięcie",
			exponent: "Wykładnik grzejników",
			limits: "Najniższa / najwyższa woda",
			correction: "Korekta komfortu",
			correction_on: "włączona, do {value} K",
			correction_off: "wyłączona",
			preview_hint: "Przeciągnij niebieski punkt — największy mróz — albo użyj strzałek; suwak przesuwa całą krzywą.",
			handle: "Punkt przy największym mrozie: {outdoor} na zewnątrz, {water} wody. Strzałki go przesuwają.",
			preview_effect: "Przy {outdoor} na zewnątrz: woda {saved} → {draft}.",
			preview_note: "Podgląd niczego nie zmienia w kotle. Krzywą zmienisz w ustawieniach wtyczki; zapis z tej strony pojawi się w kolejnym kroku.",
			reset: "Wróć do zapisanej krzywej",
			loading_error: "Nie udało się odczytać krzywej: {message}",
			problem: {
				design_flow_too_low: "Woda przy największym mrozie musi być co najmniej 5 °C powyżej temperatury pokoju krzywej.",
				design_flow_above_hard_max: "Woda przy największym mrozie jest powyżej najwyższej wody: krzywa zostałaby ucięta w mróz.",
				design_outdoor_too_warm: "Największy mróz musi być co najmniej 10 °C poniżej temperatury pokoju krzywej.",
				hard_min_not_below_design_flow: "Najniższa woda musi być poniżej wody przy największym mrozie.",
				hard_min_above_max: "Najniższa woda jest powyżej najwyższej wody obiegu albo kotła.",
				invalid_curve: "Z tych wartości nie da się zrobić krzywej.",
				out_of_range: "wartość jest poza tym, co przyjmują ustawienia.",
				offset_advanced: "przesunięcie ustawia się na poziomie zaawansowanym ustawień wtyczki.",
				needs_settings: "ustawienia potrzebują przy tym zapisie Ciebie — otwórz je, żeby dokończyć.",
				other: "ustawienia odmówiły ({key})."
			},
			save: "Zapisz",
			save_title: "Zapisać krzywą?",
			save_body: "Ustawienia wtyczki zapiszą ją z własnymi sprawdzeniami i przeładują się raz; sterowanie pójdzie dalej z nową krzywą.",
			save_point: "Punkt przy największym mrozie",
			saving: "Zapisywanie…",
			saved: "Zapisano: wtyczka przeładowuje ustawienia.",
			refused: "Nie zapisano: {reason}",
			open_settings: "Otwórz ustawienia wtyczki",
			admin_only: "Krzywą może zapisać tylko administrator."
		},
		timeline: {
			title: "Ostatnie 24 h",
			hint: "Przewiń albo odtwórz dobę: kafelki, schemat, pokoje i krzywa pokażą tamtą chwilę.",
			play: "Odtwórz dobę",
			pause: "Zatrzymaj",
			now: "Teraz",
			slider: "Chwila doby",
			legend_requested: "prośba wtyczki",
			legend_flow: "zasilanie",
			legend_return: "powrót",
			legend_heat: "palenie: ogrzewanie",
			legend_hot_water: "palenie: ciepła woda",
			loading: "Wczytywanie historii…",
			no_history: "Brak historii: recorder nie zapisuje tych encji.",
			error: "Nie udało się odczytać historii: {message}"
		},
		tabs: {
			overview: "Przegląd",
			burner: "Palnik",
			label: "Widoki strony",
			use: "Zużycie"
		},
		burner: {
			starts_per_hour: "Starty na godzinę",
			starts_per_hour_detail: "ogrzewanie, ostatnie 24 h",
			median_burn: "Typowe palenie",
			median_burn_detail: "mediana palenia ogrzewania",
			short_burn_share: "Krótkie palenia",
			short_burn_share_detail: "palenia ogrzewania krótsze niż {value} min",
			burner_hours: "Godziny palnika",
			burner_hours_detail: "ogrzewanie, ostatnie 24 h",
			condensing_share: "Kondensacja",
			condensing_share_detail: "czasu palenia ogrzewania z powrotem poniżej 55 °C",
			timeline: "Palenia — ostatnie 24 h",
			heat: "ogrzewanie",
			dhw: "ciepła woda",
			unknown: "nieznany rodzaj",
			burn: "{from}–{to} · {minutes} min · {kind}",
			summary: "{count} paleń w ostatnich 24 h: ogrzewanie {heat}, ciepła woda {dhw}, nieznany rodzaj {unknown}.",
			lengths: "Jak długo trwały palenia ogrzewania",
			lengths_hint: "Palenia z ostatnich 24 h według długości. Krótkie palenia zużywają kocioł i gaz.",
			short: "{count} krótkich (poniżej {value} min)",
			minutes: "minuty",
			count: "{label} min: {count}",
			as_of: "Tak, jak widzi je analiza monitora z {time}.",
			none: "Brak paleń w ostatnich 24 h.",
			no_analysis: "Monitor nie przeanalizował jeszcze paleń.",
			error: "Nie udało się odczytać paleń: {message}"
		},
		use: {
			gas_per_degree_day: "Gaz na stopniodzień",
			gas_per_degree_day_detail: "ostatnie 7 dni — z licznika gazu albo oszacowane",
			degree_days: "Stopniodni",
			degree_days_detail: "ostatnie 7 dni, od progu grzania",
			weeks: "Gaz na stopniodzień — 12 tygodni",
			weeks_hint: "Ile gazu dom potrzebuje na każdy stopień chłodu. Pogoda się wyrównuje, więc tygodnie da się porównać. Niżej = lepiej.",
			week: "Tydzień od {date}: {value}",
			week_none: "Tydzień od {date}: nieznany — brak gazu w któryś dzień albo za ciepło",
			weeks_none: "Jeszcze żadnego tygodnia: podsumowania dni przybywają dzień po dniu.",
			change: "Wczoraj wobec przedwczoraj",
			change_hint: "Skąd wzięła się różnica.",
			total: "{sign}{value} {unit} ({percent})",
			less: "mniej",
			more: "więcej",
			weather: "Pogoda",
			dhw: "Ciepła woda",
			settings: "Ustawienia",
			other: "Reszta",
			normal: "w granicach zwykłej zmienności dzień do dnia",
			not_judged: "nie oceniono",
			no_report: "Jeszcze bez raportu: potrzebuje dwóch dni danych.",
			error: "Nie udało się odczytać zużycia: {message}"
		}
	}
};
function je(e) {
	if (!e) return L.en;
	let t = e.toLowerCase();
	return L[t] ?? L[t.split("-")[0]] ?? L.en;
}
function Me(e, t) {
	let n = e;
	for (let e of t.split(".")) {
		if (typeof n != "object") return;
		n = n[e];
	}
	return typeof n == "string" ? n : void 0;
}
function R(e, t, n) {
	let r = Me(je(e), t) ?? Me(L.en, t) ?? t;
	return n ? r.replace(/\{(\w+)\}/g, (e, t) => n[t] ?? e) : r;
}
// src/burner.ts
var Ne = [
	0,
	5,
	10,
	15,
	20,
	30,
	45
];
function Pe(e, t, n) {
	return e.filter((e) => e.end > t - n && e.start <= t).sort((e, t) => e.start - t.start);
}
function Fe(e, t) {
	let n = [.../* @__PURE__ */ new Set([...Ne, t])].filter((e) => e >= 0).sort((e, t) => e - t), r = n.map((e, r) => ({
		from: e,
		to: r + 1 < n.length ? n[r + 1] : Infinity,
		count: 0,
		short: e < t
	}));
	for (let t of e) {
		if (t.kind !== "ch") continue;
		let e = (t.end - t.start) / 60, n = r.find((t) => e >= t.from && e < t.to);
		n && (n.count += 1);
	}
	return r;
}
function Ie(e) {
	return Math.max(1, Math.round((e.end - e.start) / 60));
}
// src/format.ts
var Le = /* @__PURE__ */ new Set([
	"unknown",
	"unavailable",
	"none",
	""
]);
function z(e) {
	if (e == null || Le.has(e)) return null;
	let t = Number(e);
	return Number.isFinite(t) ? t : null;
}
function B(e, t, n = 1) {
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
function V(e, t) {
	return e == null ? "—" : `${B(e, t, 1)} °C`;
}
// src/live.ts
var Re = 55;
function H(e, t) {
	return t ? e.states[t] : void 0;
}
function U(e, t) {
	return H(e, e.installation.signals[t]);
}
function ze(e, t) {
	return H(e, e.installation.entities[t]);
}
function Be(e) {
	return [...new Set(e.circuits.flatMap((e) => e.zones.map((e) => e.entity_id)))];
}
function Ve(e) {
	let t = ze(e, "demand_count")?.attributes.calling_zones;
	return Array.isArray(t) ? t.filter((e) => typeof e == "string") : [];
}
function He(e) {
	return U(e, "flame")?.state === "on";
}
function Ue(e) {
	let { t } = e, n = He(e), r = ze(e, "control_state");
	if (r && r.state !== "unavailable") {
		let t = r.attributes.reasons_text;
		return {
			title: e.stateText(r),
			detail: typeof t == "string" ? t : "",
			flame: n,
			code: r.state
		};
	}
	let i = U(e, "flame") ? t(n ? "status.burner_on" : "status.burner_off") : t("status.monitoring_detail");
	return {
		title: t("status.monitoring"),
		detail: i,
		flame: n,
		code: "monitoring"
	};
}
function We(e) {
	let t = e.installation.entities.control, n = H(e, t);
	return !t || !n ? null : {
		entityId: t,
		on: n.state === "on",
		available: n.state !== "unavailable"
	};
}
function Ge(e) {
	let { t, language: n, installation: r } = e, i = [], a = ze(e, "control_setpoint");
	if (a) {
		let e = z(String(a.attributes.requested ?? "")), r = z(String(a.attributes.read_back ?? "")), o = e != null && r != null && Math.abs(e - r) < .5;
		i.push({
			key: "water",
			label: t("tiles.water"),
			value: V(e, n),
			detail: t(e == null ? "tiles.water_none" : o ? "tiles.water_confirmed" : "tiles.water_waiting")
		});
	}
	let o = U(e, "flow");
	o && i.push({
		key: "flow",
		label: t("tiles.flow"),
		value: V(z(o.state), n),
		detail: t("tiles.flow_detail")
	});
	let s = U(e, "return");
	if (s) {
		let e = z(s.state), a = r.boiler.condensing && e != null && e < Re;
		i.push({
			key: "return",
			label: t("tiles.return"),
			value: V(e, n),
			detail: t(a ? "tiles.return_condensing" : "tiles.return_detail")
		});
	}
	let c = U(e, "outdoor"), l = H(e, r.weather), u = l ? z(String(l.attributes.temperature ?? "")) : null;
	if (c || u != null) {
		let e = c ? z(c.state) : null;
		i.push({
			key: "outdoor",
			label: t("tiles.outdoor"),
			value: V(e ?? u, n),
			detail: t(e == null ? "tiles.outdoor_weather" : "tiles.outdoor_sensor")
		});
	}
	let d = U(e, "flame");
	if (d) {
		let r = d.state === "on", a = z(U(e, "modulation")?.state), o = U(e, "dhw_active")?.state === "on";
		i.push({
			key: "flame",
			label: t("tiles.flame"),
			value: t(r ? "tiles.flame_on" : "tiles.flame_off"),
			detail: r && o ? t("tiles.flame_hot_water") : r && a != null ? t("tiles.flame_modulation", { value: B(a, n, 0) }) : ""
		});
	}
	let f = Be(r);
	return f.length && ze(e, "demand_count") && i.push({
		key: "rooms",
		label: t("tiles.rooms"),
		value: t("tiles.rooms_value", {
			calling: String(Ve(e).filter((e) => f.includes(e)).length),
			total: String(f.length)
		}),
		detail: t("tiles.rooms_detail")
	}), i;
}
function Ke(e) {
	return {
		status: Ue(e),
		control: We(e),
		tiles: Ge(e)
	};
}
// src/timeline.ts
var qe = 36e5, Je = 24 * qe;
function Ye(e) {
	let t = [
		"control_state",
		"control_setpoint",
		"demand_count",
		"boiler_called",
		"control"
	].map((t) => e.entities[t]).filter((e) => !!e);
	return [.../* @__PURE__ */ new Set([
		...Object.values(e.signals),
		...t,
		...Be(e),
		...e.weather ? [e.weather] : []
	])];
}
function Xe(e) {
	let t = {};
	for (let [n, r] of Object.entries(e)) {
		let e = {};
		t[n] = [...r].sort((e, t) => e.lu - t.lu).map((t) => (t.a && (e = t.a), {
			t: t.lu * 1e3,
			state: t.s,
			attributes: e
		}));
	}
	return t;
}
function Ze(e, t) {
	if (!e?.length || e[0].t > t) return;
	let n = 0, r = e.length - 1;
	for (; n < r;) {
		let i = n + r + 1 >> 1;
		e[i].t <= t ? n = i : r = i - 1;
	}
	return e[n];
}
function Qe(e, t, n) {
	let r = { ...n };
	for (let [i, a] of Object.entries(e)) {
		if (!a.length) continue;
		let e = Ze(a, t), o = new Date(e?.t ?? t).toISOString();
		r[i] = {
			entity_id: i,
			state: e?.state ?? "unknown",
			attributes: e?.attributes ?? n[i]?.attributes ?? {},
			last_changed: o,
			last_updated: o
		};
	}
	return r;
}
function $e(e, t) {
	return (e ?? []).map((e) => {
		let n = t ? e.attributes[t] : e.state, r = typeof n == "number" ? n : z(typeof n == "string" ? n : null);
		return [e.t, Number.isFinite(r) ? r : null];
	});
}
function W(e) {
	return e.some(([, e]) => e != null);
}
function et(e, t) {
	let n = null;
	for (let [r, i] of e) {
		if (r > t) break;
		n = i;
	}
	return n;
}
function tt(e, t, n, r) {
	let i = [], a = null, o = e ?? [], s = Ze(o, t);
	s && r(s.state) && (a = t);
	for (let e of o) e.t <= t || e.t > n || (r(e.state) && a == null && (a = e.t), !r(e.state) && a != null && (i.push([a, e.t]), a = null));
	return a != null && i.push([a, n]), i;
}
function nt(e, t, n, r, i, a, o) {
	let s = (e) => (Math.min(n, Math.max(t, e)) - t) / (n - t) * a, c = (e) => (i - e) / (i - r) * o, l = "", u = !1;
	for (let r = 0; r < e.length; r++) {
		let [i, a] = e[r], o = r + 1 < e.length ? e[r + 1][0] : n;
		o <= t || i >= n || (a == null ? u = !1 : (l += `${u ? "L" : "M"}${s(Math.max(i, t)).toFixed(1)} ${c(a).toFixed(1)}L${s(o).toFixed(1)} ${c(a).toFixed(1)}`, u = !0));
	}
	return l;
}
function rt(e) {
	let t = e.flat().flatMap(([, e]) => e == null ? [] : [e]);
	if (!t.length) return [20, 60];
	let n = Math.floor((Math.min(...t) - 2) / 10) * 10, r = Math.ceil((Math.max(...t) + 2) / 10) * 10;
	return r - n < 20 && (r = n + 20), [n, r];
}
function it(e, t, n, r) {
	let i = [], a = Math.ceil(e / (n * qe)) * n * qe;
	for (let e = a; e <= t; e += n * qe) i.push({
		t: e,
		label: G(e, r)
	});
	return i;
}
function G(e, t) {
	try {
		return new Intl.DateTimeFormat(t, {
			hour: "2-digit",
			minute: "2-digit"
		}).format(e);
	} catch {
		let t = new Date(e);
		return `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
	}
}
// src/burner-view.ts
var at = "vtherm-smart-boiler-burner", ot = 86400, st = 3e5, ct = [
	["starts_per_hour", 1],
	["median_burn", 0],
	["short_burn_share", 0],
	["burner_hours", 1],
	["condensing_share", 0]
], lt = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			answer: { state: !0 },
			error: { state: !0 },
			hovered: { state: !0 }
		};
	}
	constructor() {
		super(), this.answer = null, this.error = "", this.hovered = "";
	}
	connectedCallback() {
		super.connectedCallback(), this.timer = window.setInterval(() => void this.fetchBurns(), st);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), window.clearInterval(this.timer);
	}
	firstUpdated() {
		this.fetchBurns();
	}
	async fetchBurns() {
		if (this.hass) try {
			this.answer = await this.hass.callWS({ type: "vtherm_smart_boiler/burns" }), this.error = "";
		} catch (e) {
			let t = e?.message;
			this.error = this.t("burner.error", { message: typeof t == "string" ? t : String(e) });
		}
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	get language() {
		return this.hass?.locale?.language ?? this.hass?.language ?? "en";
	}
	tiles() {
		let e = this.hass, t = this.installation, n = this.language, r = B(t.short_burn_min, n, 0);
		return ct.flatMap(([i, a]) => {
			let o = e.states[t.entities[i] ?? ""];
			if (!o) return [];
			let s = z(o.state), c = o.attributes.unit_of_measurement, l = s == null ? "—" : `${B(s, n, a)}${typeof c == "string" && c !== "/h" ? ` ${c}` : ""}`;
			return [A`<div class="card tile">
          <div class="tile-label">${this.t(`burner.${i}`)}</div>
          <div class="tile-value">${l}</div>
          <div class="muted small">${this.t(`burner.${i}_detail`, { value: r })}</div>
        </div>`];
		});
	}
	burnText(e, t) {
		return this.t("burner.burn", {
			from: G(e.start * 1e3, t),
			to: G(e.end * 1e3, t),
			minutes: String(Ie(e)),
			kind: this.t(`burner.${e.kind === "ch" ? "heat" : e.kind}`)
		});
	}
	render() {
		if (!this.hass || !this.installation) return M;
		let e = this.language, t = this.answer, n = Date.now() / 1e3, r = n - ot, i = t ? Pe(t.burns, n, ot) : [], a = Fe(i, this.installation.short_burn_min), o = Math.max(4, ...a.map((e) => e.count)), s = a.filter((e) => e.short).reduce((e, t) => e + t.count, 0), c = (e) => `${((Math.max(e, r) - r) / ot * 100).toFixed(3)}%`, l = (e) => `${Math.max(.25, (e.end - Math.max(e.start, r)) / ot * 100).toFixed(3)}%`, u = (e) => String(i.filter((t) => t.kind === e).length), d = (t, n) => n === Infinity ? `${B(t, e, 0)}+` : `${B(t, e, 0)}–${B(n, e, 0)}`;
		return A`
      <section class="tiles">${this.tiles()}</section>
      <section class="card">
        <div class="head">
          <h3>${this.t("burner.timeline")}</h3>
          <div class="legend">
            <span><i class="box ch"></i>${this.t("burner.heat")}</span>
            <span><i class="box dhw"></i>${this.t("burner.dhw")}</span>
            <span><i class="box unknown"></i>${this.t("burner.unknown")}</span>
          </div>
        </div>
        ${this.error ? A`<p class="error" role="alert">${this.error}</p>` : t ? t.at == null ? A`<p class="muted">${this.t("burner.no_analysis")}</p>` : A`
                  <div
                    class="strip"
                    role="img"
                    aria-label=${this.t("burner.summary", {
			count: String(i.length),
			heat: u("ch"),
			dhw: u("dhw"),
			unknown: u("unknown")
		})}
                  >
                    ${Array.from({ length: 5 }, (e, t) => A`<span class="hour" style="left: ${(t + 1) * 4 / 24 * 100}%"></span>`)}
                    ${i.map((t) => A`<span
                        class="burn ${t.kind}"
                        style="left: ${c(t.start)}; width: ${l(t)}"
                        @mouseenter=${() => this.hovered = this.burnText(t, e)}
                        @mouseleave=${() => this.hovered = ""}
                      ></span>`)}
                  </div>
                  <div class="xaxis" aria-hidden="true">
                    ${it(r * 1e3, n * 1e3, this.offsetWidth < 560 ? 8 : 4, e).map((e) => A`<span style="left: ${c(e.t / 1e3)}">${e.label}</span>`)}
                  </div>
                  <p class="muted small hover" aria-live="polite">
                    ${this.hovered || (i.length ? this.t("burner.as_of", { time: G(t.at * 1e3, e) }) : this.t("burner.none"))}
                  </p>
                ` : M}
      </section>
      ${t?.at == null ? M : A`<section class="card">
            <div class="head">
              <h3>${this.t("burner.lengths")}</h3>
              ${s ? A`<span class="chip warn">${this.t("burner.short", {
			count: String(s),
			value: B(this.installation.short_burn_min, e, 0)
		})}</span>` : M}
            </div>
            <p class="muted small">${this.t("burner.lengths_hint")}</p>
            <div class="bars" role="img" aria-label=${a.map((e) => this.t("burner.count", {
			label: d(e.from, e.to),
			count: String(e.count)
		})).join("; ")}>
              ${a.map((e) => A`<div class="bar-cell">
                  <span class="bar-count">${e.count || ""}</span>
                  <span class="bar ${e.short ? "short" : ""}" style="height: ${(e.count / o * 100).toFixed(1)}%"></span>
                </div>`)}
            </div>
            <div class="bar-labels" aria-hidden="true">
              ${a.map((e) => A`<span>${d(e.from, e.to)}</span>`)}
            </div>
            <div class="muted small center">${this.t("burner.minutes")}</div>
          </section>`}
    `;
	}
	static {
		this.styles = o`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      --sb-ch: #2a78d6;
      --sb-dhw: #eb6834;
      --sb-unknown: #9c9a93;
      --sb-warn: #fab219;
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
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px 16px;
      margin-bottom: 10px;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .center {
      text-align: center;
    }
    .error {
      color: var(--error-color, #db4437);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 14px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .box {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .ch {
      background: var(--sb-ch);
    }
    .dhw {
      background: var(--sb-dhw);
    }
    .unknown {
      background: var(--sb-unknown);
    }
    .strip {
      position: relative;
      height: 56px;
      border-radius: 6px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .hour {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .burn {
      position: absolute;
      top: 6px;
      bottom: 6px;
      border-radius: 3px;
      min-width: 2px;
    }
    .burn:hover {
      outline: 2px solid var(--primary-text-color);
      outline-offset: 1px;
    }
    .xaxis {
      position: relative;
      height: 16px;
      margin-top: 6px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
    .hover {
      min-height: 16px;
      margin: 8px 0 0;
    }
    .chip {
      font-size: 12px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 999px;
    }
    .chip.warn {
      background: rgba(250, 178, 25, 0.18);
      color: var(--primary-text-color);
      box-shadow: inset 0 0 0 1px var(--sb-warn);
    }
    .bars {
      position: relative;
      height: 180px;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 10px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
      margin-top: 12px;
    }
    .bar-cell {
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: stretch;
    }
    .bar {
      display: block;
      border-radius: 4px 4px 0 0;
      background: var(--sb-ch);
      min-height: 0;
    }
    .bar.short {
      background: var(--sb-warn);
    }
    .bar-count {
      text-align: center;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 2px;
      font-variant-numeric: tabular-nums;
    }
    .bar-labels {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 10px;
      font-size: 11px;
      color: var(--secondary-text-color);
      text-align: center;
      margin-top: 6px;
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-burner") || customElements.define(at, lt);
// src/curve.ts
function ut(e) {
	return {
		outdoorFrom: Math.min(-20, Math.floor(e.design_outdoor / 5) * 5 - 5),
		outdoorTo: 20,
		waterFrom: 15,
		waterTo: Math.max(75, Math.ceil(e.hard_max / 5) * 5 + 5)
	};
}
function K(e, t, n) {
	return {
		x: (t - e.outdoorFrom) / (e.outdoorTo - e.outdoorFrom),
		y: (e.waterTo - n) / (e.waterTo - e.waterFrom)
	};
}
function dt(e, t, n, r) {
	return t.map(([t, i], a) => {
		let { x: o, y: s } = K(e, t, i);
		return `${a ? "L" : "M"}${(o * n).toFixed(1)} ${(s * r).toFixed(1)}`;
	}).join("");
}
function ft(e, t, n) {
	let r = [];
	for (let i = Math.ceil(e / n) * n; i <= t + 1e-9; i += n) r.push(Math.round(i * 10) / 10);
	return r;
}
function q(e) {
	return typeof e == "number" && Number.isFinite(e) ? e : null;
}
function pt(e) {
	let t = e?.attributes ?? {}, n = q(t.curve_outdoor), r = q(t.target);
	return n == null || r == null ? null : {
		outdoor: n,
		water: r,
		room: q(t.curve_room)
	};
}
function mt(e) {
	let t = [], n = -Infinity, r = {};
	for (let i of e) {
		if (i.a && (r = i.a), i.s !== "heating") continue;
		let e = q(r.curve_outdoor), a = q(r.target), o = Math.floor(i.lu / 3600);
		e != null && a != null && o !== n && (n = o, t.push([e, a]));
	}
	return t;
}
function ht(e, t, n) {
	let r = (e, t, n) => Math.min(n, Math.max(t, e)), i = e.outdoorFrom + r(t, 0, 1) * (e.outdoorTo - e.outdoorFrom), a = e.waterTo - r(n, 0, 1) * (e.waterTo - e.waterFrom);
	return {
		design_outdoor: r(Math.round(i * 2) / 2, -30, -5),
		design_flow: r(Math.round(a * 2) / 2, 25, 80)
	};
}
function gt(e, t) {
	for (let n = 1; n < e.length; n++) {
		let [r, i] = e[n - 1], [a, o] = e[n];
		if (t >= r && t <= a) return a === r ? i : i + (o - i) * (t - r) / (a - r);
	}
	return null;
}
// src/curve-card.ts
var _t = "vtherm-smart-boiler-curve", J = 1e3, Y = 280, vt = 864e5, yt = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			saved: { state: !0 },
			draft: { state: !0 },
			draftAnswer: { state: !0 },
			past: { state: !0 },
			error: { state: !0 },
			confirmSave: { state: !0 },
			saving: { state: !0 },
			saveNote: { state: !0 }
		};
	}
	constructor() {
		super(), this.savedRoom = void 0, this.historyAsked = !1, this.asking = !1, this.askAgain = !1, this.saved = null, this.draft = null, this.draftAnswer = null, this.past = [], this.error = "", this.confirmSave = !1, this.saving = !1, this.saveNote = "";
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	get language() {
		return this.hass?.locale?.language ?? this.hass?.language ?? "en";
	}
	get settings() {
		return this.installation?.curve ?? null;
	}
	controlState() {
		let e = this.installation?.entities.control_state;
		return e ? this.hass?.states[e] : void 0;
	}
	room() {
		return pt(this.controlState())?.room ?? this.settings?.room ?? null;
	}
	willUpdate() {
		let e = this.settings;
		if (!this.hass || !e?.entered) return;
		let t = this.room();
		t !== this.savedRoom && (this.savedRoom = t, this.askSaved(t)), this.historyAsked || (this.historyAsked = !0, this.askHistory());
	}
	async curve(e) {
		let t = ut(this.settings);
		return this.hass.callWS({
			type: "vtherm_smart_boiler/curve",
			outdoor_from: t.outdoorFrom,
			outdoor_to: t.outdoorTo,
			step: .5,
			...e
		});
	}
	async askSaved(e) {
		try {
			let t = await this.curve(e == null ? {} : { room: e });
			this.saved = t.points, this.error = "";
		} catch (e) {
			this.error = this.t("curve.loading_error", { message: bt(e) });
		}
	}
	async askHistory() {
		let e = this.installation?.entities.control_state;
		if (!e || !this.hass) return;
		let t = /* @__PURE__ */ new Date();
		try {
			let n = await this.hass.callWS({
				type: "history/history_during_period",
				start_time: (/* @__PURE__ */ new Date(t.getTime() - 7 * vt)).toISOString(),
				end_time: t.toISOString(),
				entity_ids: [e],
				include_start_time_state: !0,
				significant_changes_only: !1,
				minimal_response: !1,
				no_attributes: !1
			});
			this.past = mt(n[e] ?? []);
		} catch {
			this.past = [];
		}
	}
	async askDraft() {
		if (this.asking) {
			this.askAgain = !0;
			return;
		}
		let e = this.draft;
		if (e) {
			this.asking = !0;
			try {
				let t = this.room();
				this.draftAnswer = await this.curve({
					...e,
					...t == null ? {} : { room: t }
				});
			} catch (e) {
				this.error = this.t("curve.loading_error", { message: bt(e) });
			} finally {
				this.asking = !1, this.askAgain && (this.askAgain = !1, this.askDraft());
			}
		}
	}
	setDraft(e) {
		this.draft && (this.draft = {
			...this.draft,
			...e
		}, this.askDraft());
	}
	togglePreview() {
		let e = this.settings;
		this.draft || !e ? (this.draft = null, this.draftAnswer = null) : (this.draft = {
			design_outdoor: e.design_outdoor,
			design_flow: e.design_flow,
			offset: e.offset
		}, this.askDraft());
	}
	onPointer(e, t) {
		let n = e.currentTarget;
		if (e.type === "pointerdown" && n.setPointerCapture(e.pointerId), !n.hasPointerCapture(e.pointerId)) return;
		if (e.type === "pointerup" || e.type === "pointercancel") {
			n.releasePointerCapture(e.pointerId);
			return;
		}
		let r = n.parentElement.getBoundingClientRect();
		this.setDraft(ht(t, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height));
	}
	onKey(e) {
		let t = this.draft;
		if (!t) return;
		let n = {
			ArrowLeft: [-.5, 0],
			ArrowRight: [.5, 0],
			ArrowUp: [0, .5],
			ArrowDown: [0, -.5]
		}[e.key];
		n && (e.preventDefault(), this.setDraft({
			design_outdoor: Math.min(-5, Math.max(-30, t.design_outdoor + n[0])),
			design_flow: Math.min(80, Math.max(25, t.design_flow + n[1]))
		}));
	}
	get isAdmin() {
		return this.hass?.user?.is_admin === !0;
	}
	canSave(e) {
		let t = this.draft;
		return !t || !this.isAdmin || this.saving || this.asking || this.draftAnswer == null || this.draftAnswer.problems.length ? !1 : t.design_outdoor !== e.design_outdoor || t.design_flow !== e.design_flow || e.advanced && t.offset !== e.offset;
	}
	reason(e) {
		let t = Object.values(e)[0] ?? "", n = this.t(`curve.problem.${t}`);
		return n === `curve.problem.${t}` ? this.t("curve.problem.other", { key: t }) : n;
	}
	async save(e) {
		this.confirmSave = !1;
		let t = this.settings, n = this.draft;
		if (e && t && n && this.hass) {
			this.saving = !0, this.saveNote = "";
			try {
				let e = await this.hass.callWS({
					type: "vtherm_smart_boiler/curve/save",
					design_outdoor: n.design_outdoor,
					design_flow: n.design_flow,
					...t.advanced ? { offset: n.offset } : {}
				});
				e.saved ? (this.saveNote = this.t("curve.saved"), this.draft = null, this.draftAnswer = null, this.dispatchEvent(new CustomEvent("installation-changed", {
					bubbles: !0,
					composed: !0
				}))) : this.saveNote = this.t("curve.refused", { reason: this.reason(e.errors) });
			} catch (e) {
				this.saveNote = this.t("curve.refused", { reason: bt(e) });
			} finally {
				this.saving = !1;
			}
		}
	}
	updated() {
		let e = this.renderRoot.querySelector("dialog");
		e && (this.confirmSave && !e.open && e.showModal(), !this.confirmSave && e.open && e.close());
	}
	render() {
		let e = this.settings;
		if (!this.hass || !this.installation) return M;
		if (!e) return this.frame(A`<p class="muted">${this.t("curve.no_curve")}</p>`);
		if (!e.entered) return this.frame(A`<p class="muted">${this.t("curve.not_entered")}</p>`);
		let t = ut(e), n = pt(this.controlState()), r = this.language, i = (e) => V(e, r), a = this.draft, o = a ? this.draftAnswer?.points ?? null : null, s = (e, n) => {
			let r = K(t, e, n);
			return {
				left: `${(r.x * 100).toFixed(2)}%`,
				top: `${(r.y * 100).toFixed(2)}%`
			};
		}, c = ft(t.waterFrom + 5, t.waterTo, 10).map((e) => `M0 ${(K(t, 0, e).y * Y).toFixed(1)}H${J}`).join(""), l = K(t, 0, t.waterFrom).x * J, u = [e.hard_min, e.hard_max].map((e) => `M0 ${(K(t, 0, e).y * Y).toFixed(1)}H${J}`).join(""), d = n ? s(n.outdoor, n.water) : null, f = a ? s(a.design_outdoor, a.design_flow) : null, p = n?.outdoor ?? 0, m = this.saved ? gt(this.saved, p) : null, h = o ? gt(o, p) : null;
		return this.frame(A`
      <div class="where">
        <div class="muted small">${this.t("curve.where")}</div>
        ${n ? A`<div class="big">${i(n.outdoor)} → ${i(n.water)}</div>
              <div class="muted small">
                ${this.t("curve.where_detail", { room: i(n.room ?? e.room) })}
              </div>` : A`<div class="muted">${this.t("curve.where_none")}</div>`}
      </div>
      <div class="chart">
        <div class="yaxis" aria-hidden="true">
          ${ft(t.waterFrom + 5, t.waterTo, 10).map((e) => A`<span style="top: ${s(0, e).top}">${e}</span>`)}
        </div>
        <div class="plot-wrap">
          <div class="plot" role="img" aria-label=${n ? `${this.t("curve.where")}: ${i(n.outdoor)} → ${i(n.water)}` : this.t("curve.title")}>
            <svg viewBox="0 0 ${J} ${Y}" preserveAspectRatio="none" aria-hidden="true">
              ${ge`
                <path class="grid" d=${c + `M${l.toFixed(1)} 0V${Y}`}></path>
                <path class="limit" d=${u}></path>
                <path class=${a ? "saved" : "line"} d=${this.saved ? dt(t, this.saved, J, Y) : ""}></path>
                <path class="line" d=${o ? dt(t, o, J, Y) : ""}></path>
              `}
            </svg>
            ${this.past.map((e) => {
			let t = s(e[0], e[1]);
			return A`<span class="past" style="left: ${t.left}; top: ${t.top}"></span>`;
		})}
            <span class="limit-label" style="top: ${s(0, e.hard_max).top}"
              >${this.t("curve.highest", { value: i(e.hard_max) })}</span
            >
            <span class="limit-label" style="top: ${s(0, e.hard_min).top}"
              >${this.t("curve.lowest", { value: i(e.hard_min) })}</span
            >
            ${d ? A`<span class="now" style="left: ${d.left}; top: ${d.top}"></span>` : M}
            ${f && a ? A`<button
                  class="handle"
                  style="left: ${f.left}; top: ${f.top}"
                  aria-label=${this.t("curve.handle", {
			outdoor: i(a.design_outdoor),
			water: i(a.design_flow)
		})}
                  @pointerdown=${(e) => this.onPointer(e, t)}
                  @pointermove=${(e) => this.onPointer(e, t)}
                  @pointerup=${(e) => this.onPointer(e, t)}
                  @pointercancel=${(e) => this.onPointer(e, t)}
                  @keydown=${(e) => this.onKey(e)}
                ></button>` : M}
          </div>
          <div class="xaxis" aria-hidden="true">
            ${ft(t.outdoorFrom, t.outdoorTo, 10).map((e) => A`<span style="left: ${s(e, t.waterFrom).left}">${B(e, r, 0)}</span>`)}
          </div>
          <div class="muted small center">${this.t("curve.axis")}</div>
        </div>
      </div>
      <div class="legend">
        <span><i class="dot now-dot"></i>${this.t("curve.legend_now")}</span>
        <span><i class="dot past-dot"></i>${this.t("curve.legend_days")}</span>
        ${a ? A`<span><i class="dash"></i>${this.t("curve.legend_saved")}</span>
              <span><i class="solid"></i>${this.t("curve.legend_draft")}</span>` : M}
      </div>
      ${a ? A`<div class="preview">
            <p class="muted small">${this.t("curve.preview_hint")}</p>
            ${e.advanced ? A`<label class="field">
              <span>${this.t("curve.offset")} <b>${B(a.offset, r, 1)} K</b></span>
              <input
                type="range"
                min="-5"
                max="5"
                step="0.5"
                .value=${String(a.offset)}
                @input=${(e) => this.setDraft({ offset: Number(e.target.value) })}
              />
            </label>` : M}
            ${m != null && h != null ? A`<p>${this.t("curve.preview_effect", {
			outdoor: i(p),
			saved: i(m),
			draft: i(h)
		})}</p>` : M}
            ${(this.draftAnswer?.problems ?? []).map((e) => A`<p class="problem" role="alert">${this.t(`curve.problem.${e}`)}</p>`)}
            <div class="actions">
              <button
                class="primary"
                ?disabled=${!this.canSave(e)}
                @click=${() => {
			this.saveNote = "", this.confirmSave = !0;
		}}
              >
                ${this.saving ? this.t("curve.saving") : this.t("curve.save")}
              </button>
              <button class="text" @click=${() => this.setDraft({
			design_outdoor: e.design_outdoor,
			design_flow: e.design_flow,
			offset: e.offset
		})}>
                ${this.t("curve.reset")}
              </button>
            </div>
            ${this.isAdmin ? M : A`<p class="muted small">${this.t("curve.admin_only")}</p>`}
            <p class="muted small">${this.t("curve.preview_note")}</p>
            <dialog aria-labelledby="save-title" @cancel=${() => this.confirmSave = !1}>
              <h2 id="save-title">${this.t("curve.save_title")}</h2>
              <dl>
                <dt>${this.t("curve.save_point")}</dt>
                <dd>${i(e.design_outdoor)} → ${i(e.design_flow)}<br />${i(a.design_outdoor)} → ${i(a.design_flow)}</dd>
                ${e.advanced ? A`<dt>${this.t("curve.offset")}</dt>
                      <dd>${B(e.offset, r, 1)} K → ${B(a.offset, r, 1)} K</dd>` : M}
              </dl>
              <p class="muted">${this.t("curve.save_body")}</p>
              <div class="actions end">
                <button class="text" @click=${() => this.save(!1)}>${this.t("control.cancel")}</button>
                <button class="primary" @click=${() => this.save(!0)}>${this.t("curve.save")}</button>
              </div>
            </dialog>
          </div>` : A`<dl>
            <dt>${this.t("curve.design_point")}</dt>
            <dd>${i(e.design_outdoor)} → ${i(e.design_flow)}</dd>
            <dt>${this.t("curve.room")}</dt>
            <dd>${e.room_auto ? this.t("curve.room_auto", { value: i(this.room()) }) : i(e.room)}</dd>
            <dt>${this.t("curve.offset")}</dt>
            <dd>${B(e.offset, r, 1)} K</dd>
            <dt>${this.t("curve.exponent")}</dt>
            <dd>${B(e.exponent, r, 2)}</dd>
            <dt>${this.t("curve.limits")}</dt>
            <dd>${i(e.hard_min)} / ${i(e.hard_max)}</dd>
            <dt>${this.t("curve.correction")}</dt>
            <dd>
              ${e.comfort_correction ? this.t("curve.correction_on", { value: B(e.correction_max_k, r, 0) }) : this.t("curve.correction_off")}
            </dd>
          </dl>`}
      ${this.saveNote ? A`<p class="note" role="status">${this.saveNote}</p>` : M}
      ${this.error ? A`<p class="problem" role="alert">${this.error}</p>` : M}
      <a class="settings" href="/config/integrations/integration/vtherm_smart_boiler">${this.t("curve.open_settings")}</a>
    `);
	}
	frame(e) {
		let t = this.settings;
		return A`<section class="card">
      <div class="head">
        <h3>${this.t("curve.title")}</h3>
        ${t?.entered ? A`<button class="outline" aria-pressed=${this.draft ? "true" : "false"} @click=${() => this.togglePreview()}>
              ${this.draft ? this.t("curve.preview_close") : this.t("curve.preview")}
            </button>` : M}
      </div>
      ${e}
    </section>`;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      --sb-curve: #2a78d6;
      --sb-now: #eb6834;
      --sb-past: #9c9a93;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .center {
      text-align: center;
      margin-top: 4px;
    }
    .where {
      margin: 10px 0 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
    }
    .big {
      font-size: 22px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .chart {
      display: flex;
      gap: 6px;
    }
    .yaxis {
      position: relative;
      width: 26px;
      flex: none;
      height: 280px;
    }
    .yaxis span {
      position: absolute;
      right: 0;
      transform: translateY(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .plot-wrap {
      flex: 1;
      min-width: 0;
    }
    .plot {
      position: relative;
      height: 280px;
    }
    .plot svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: visible;
    }
    .grid,
    .limit,
    .line,
    .saved {
      fill: none;
      vector-effect: non-scaling-stroke;
      stroke-linejoin: round;
      stroke-linecap: round;
    }
    .grid {
      stroke: var(--divider-color, rgba(0, 0, 0, 0.12));
      stroke-width: 1px;
    }
    .limit {
      stroke: var(--secondary-text-color);
      stroke-width: 1px;
      stroke-dasharray: 6 5;
    }
    .line {
      stroke: var(--sb-curve);
      stroke-width: 2.5px;
    }
    .saved {
      stroke: var(--secondary-text-color);
      stroke-width: 2px;
      stroke-dasharray: 6 5;
    }
    .past {
      position: absolute;
      width: 7px;
      height: 7px;
      margin: -3.5px 0 0 -3.5px;
      border-radius: 50%;
      background: var(--sb-past);
      opacity: 0.7;
      pointer-events: none;
    }
    .now {
      position: absolute;
      width: 16px;
      height: 16px;
      margin: -8px 0 0 -8px;
      border-radius: 50%;
      background: var(--sb-now);
      box-shadow: 0 0 0 3px var(--card-background-color, #fff), 0 0 0 4px var(--sb-now);
      pointer-events: none;
    }
    .handle {
      position: absolute;
      width: 28px;
      height: 28px;
      margin: -14px 0 0 -14px;
      border-radius: 50%;
      border: 0;
      padding: 0;
      background: var(--sb-curve);
      box-shadow: 0 0 0 4px var(--card-background-color, #fff), 0 0 0 5px var(--sb-curve), 0 4px 12px rgba(0, 0, 0, 0.25);
      cursor: grab;
      touch-action: none;
      z-index: 2;
    }
    .handle:focus-visible {
      outline: 3px solid var(--primary-text-color);
      outline-offset: 6px;
    }
    .limit-label {
      position: absolute;
      right: 2px;
      transform: translateY(-115%);
      font-size: 11px;
      color: var(--secondary-text-color);
      pointer-events: none;
    }
    .xaxis {
      position: relative;
      height: 16px;
      margin-top: 4px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 14px;
      font-size: 12px;
      color: var(--secondary-text-color);
      margin: 8px 0 12px 32px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
    }
    .now-dot {
      background: var(--sb-now);
    }
    .past-dot {
      background: var(--sb-past);
    }
    .dash,
    .solid {
      display: inline-block;
      width: 16px;
      border-top: 2px solid var(--sb-curve);
    }
    .dash {
      border-top: 2px dashed var(--secondary-text-color);
    }
    dl {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 6px 16px;
      margin: 0;
    }
    dt {
      color: var(--secondary-text-color);
      font-size: 13px;
    }
    dd {
      margin: 0;
      font-weight: 600;
      font-size: 13px;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .preview {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .preview p {
      margin: 0;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 13px;
    }
    .field input {
      width: 100%;
      accent-color: var(--primary-color);
    }
    .problem {
      color: var(--error-color, #db4437);
      font-size: 13px;
    }
    button.outline,
    button.text {
      appearance: none;
      border-radius: 10px;
      min-height: 36px;
      padding: 0 14px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      background: transparent;
      color: var(--primary-color);
    }
    button.outline {
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
    }
    button.outline[aria-pressed="true"] {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
    }
    button.text {
      border: 0;
      align-self: flex-start;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .actions.end {
      justify-content: flex-end;
      margin-top: 16px;
    }
    button.primary {
      appearance: none;
      border: 0;
      border-radius: 10px;
      min-height: 40px;
      padding: 0 16px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    button.primary:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .note {
      font-size: 13px;
      margin: 10px 0 0;
    }
    .settings {
      display: inline-block;
      margin-top: 12px;
      font-size: 13px;
      color: var(--primary-color);
    }
    dialog {
      border: 0;
      border-radius: var(--ha-dialog-border-radius, 16px);
      padding: 24px;
      max-width: 440px;
      width: calc(100% - 32px);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-size: 14px;
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.45);
    }
    dialog h2 {
      margin: 0 0 12px;
      font-size: 20px;
    }
    dialog p {
      margin: 12px 0 0;
    }
  `;
	}
};
function bt(e) {
	let t = e?.message;
	return typeof t == "string" ? t : String(e);
}
customElements.get("vtherm-smart-boiler-curve") || customElements.define(_t, yt);
// src/schematic.ts
var X = {
	x: 0,
	y: 70,
	width: 1e3,
	height: 500
}, xt = 440, St = 540, Z = 150, Ct = 470;
function wt(e) {
	switch (e.type) {
		case "single_tank": return "tank";
		case "combi":
		case "combi_tank": return "instant";
		case "single": return "none";
	}
	return e.dhw === "storage" ? "tank" : e.dhw === "combi" ? "instant" : "none";
}
function Tt(e) {
	switch (e.control) {
		case "passive_fixed": return "fixed_valve";
		case "separate": return "other";
		case "through_boiler": return "boiler_mixed";
		default: return "direct";
	}
}
function Et(e) {
	return e.zones.some((e) => e.emitter === "underfloor") ? "floor" : "radiator";
}
function Dt(e) {
	return ((t) => e.states[e.installation.signals[t] ?? ""])("dhw_active")?.state === "on" ? "dhw" : e.states[e.installation.entities.boiler_called ?? ""]?.state === "on" || Ve(e).length > 0 ? "heat" : "idle";
}
function Ot(e, t, n) {
	return `M${e - n} ${t}a${n} ${n} 0 1 0 ${2 * n} 0a${n} ${n} 0 1 0 ${-2 * n} 0`;
}
function kt(e, t, n) {
	let r = 8.25;
	switch (n) {
		case "left": return `M${e - 11} ${t - r}L${e} ${t}L${e - 11} ${t + r}Z`;
		case "right": return `M${e + 11} ${t - r}L${e} ${t}L${e + 11} ${t + r}Z`;
		case "top": return `M${e - r} ${t - 11}L${e} ${t}L${e + r} ${t - 11}Z`;
		case "bottom": return `M${e - r} ${t + 11}L${e} ${t}L${e + r} ${t + 11}Z`;
	}
}
function At() {
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
function jt(e, t, n) {
	let r = At(), i = (e, t, n) => {
		r[t] += e, n && (r.flow += e);
	}, a = t === "heat", o = wt(e.boiler), s = o === "tank", c = t === "dhw" && s, l = St / Math.max(1, e.circuits.length), u = e.circuits.map((e, t) => ({
		id: e.id,
		name: e.name,
		kind: Tt(e),
		emitter: Et(e),
		active: a && n.has(e.id),
		cx: xt + l * (t + .5),
		setting: e.fixed_temperature,
		need: e.needed,
		zones: [...new Set(e.zones.map((e) => e.entity_id))]
	})), d = u.length ? u[u.length - 1].cx - 25 : 300, f = u.length ? u[u.length - 1].cx + 35 : 300;
	r.body += "M60 124a14 14 0 0 1 14-14h122a14 14 0 0 1 14 14v222a14 14 0 0 1-14 14h-122a14 14 0 0 1-14-14Z";
	let p = a || c;
	if (i(`M210 ${Z}H300`, p ? "red" : "gray", p), i(`M300 ${Z}H${d}`, a ? "red" : "gray", a), i(`M${f} ${Ct}H300`, a ? "blue" : "gray", a), i(`M300 ${Ct}H135V360`, p ? "blue" : "gray", p), s) {
		r.body += "M255 205a45 10 0 0 1 90 0V410a45 10 0 0 1-90 0Z", i("M300 161V228", c ? "red" : "gray", c);
		let e = "M300 228H272V243H328V258H272V273H328V288H272V303H328V318H272V333H328V348H300V412";
		c ? (r.coilOn += e, r.flow += e) : r.coilOff += e, i(`M300 412V${Ct}`, c ? "blue" : "gray", c), i("M326 199V178", "red", !1), r.arrRed += "M318 180L326 166L334 180Z", i("M398 392H352", "blue", !1), r.arrBlue += "M354 384L341 392L354 400Z", r[p ? "valveOn" : "valveOff"] += kt(300, Z, "left"), r[a ? "valveOn" : "valveOff"] += kt(300, Z, "right"), r[c ? "valveOn" : "valveOff"] += kt(300, Z, "bottom");
	} else o === "instant" && (i("M60 300H30", "red", t === "dhw"), r.arrRed += "M32 292L18 300L32 308Z", i("M16 330H50", "blue", t === "dhw"), r.arrBlue += "M48 322L62 330L48 338Z");
	for (let e of u) {
		let t = e.cx - 25, n = e.cx + 35, a = e.active, o = e.kind !== "direct";
		if (o) {
			i(`M${t} ${Z}V194`, a ? "red" : "gray", a), i(`M${t} 216V290`, a ? "mix" : "gray", a);
			for (let e of [
				"top",
				"bottom",
				"left"
			]) r[a ? "valveOn" : "valveOff"] += kt(t, 205, e);
			i(`M${n} 432H${e.cx - 68}V205H${t - 11}`, a ? "blue" : "gray", a);
		} else i(`M${t} ${Z}V290`, a ? "red" : "gray", a);
		if (r.pumps += Ot(t, 252, 13), r[a ? "pumpOn" : "pumpOff"] += `M${t - 7} 246L${t + 7} 246L${t} 260Z`, e.emitter === "radiator") {
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
		i(`M${n} 390V${Ct}`, a ? "blue" : "gray", a);
	}
	return {
		paths: r,
		circuits: u,
		hotWater: o
	};
}
function Mt(e) {
	let { installation: t, states: n, language: r, t: i } = e, a = Dt(e), o = new Set(Ve(e)), { paths: s, circuits: c, hotWater: l } = jt(t, a, new Set(t.circuits.filter((e) => e.zones.some((e) => o.has(e.entity_id))).map((e) => e.id))), u = (e) => n[t.signals[e] ?? ""], d = u("flame")?.state === "on", f = [{
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
	let m = z(u("modulation")?.state);
	d && m != null && f.push({
		kind: "inside",
		x: 135,
		y: 284,
		text: i("tiles.flame_modulation", { value: B(m, r, 0) })
	});
	let h = u("flow");
	h && f.push({
		kind: "value",
		x: 252,
		y: 126,
		text: V(z(h.state), r)
	});
	let g = u("return");
	g && f.push({
		kind: "value",
		x: 220,
		y: 492,
		text: V(z(g.state), r)
	});
	let _ = u("pressure");
	if (_) {
		let e = z(_.state);
		f.push({
			kind: "value",
			x: 88,
			y: 390,
			text: e == null ? "—" : `${B(e, r, 1)} bar`
		});
	}
	let v = z(u("outdoor")?.state);
	v != null && (f.push({
		kind: "text",
		x: 925,
		y: 96,
		text: i("tiles.outdoor")
	}), f.push({
		kind: "value",
		x: 925,
		y: 120,
		text: V(v, r)
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
		let t = e.kind === "fixed_valve" && e.setting != null ? i("schematic.fixed_valve", { value: B(e.setting, r, 0) }) : e.kind === "other" && e.need != null ? i("schematic.other_need", { value: B(e.need, r, 0) }) : i(`schematic.${e.kind}`);
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
function Nt(e, t) {
	let { states: n, language: r } = e, i = new Set(Ve(e));
	return t.map((e) => e.zones.map((e) => {
		let t = n[e]?.attributes ?? {}, a = z(String(t.on_percent ?? "")), o = z(String(t.valve_open_percent ?? "")), s = a == null ? o : a * 100, c = t.friendly_name;
		return {
			entityId: e,
			name: typeof c == "string" && c ? c : e,
			temperature: V(z(String(t.current_temperature ?? "")), r),
			target: V(z(String(t.temperature ?? "")), r),
			demand: s == null ? null : Math.max(0, Math.min(100, Math.round(s))),
			calling: i.has(e)
		};
	}));
}
// src/schematic-card.ts
var Pt = "vtherm-smart-boiler-schematic", Ft = "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z";
function Q(e, t, n) {
	return `${((e - t) / n * 100).toFixed(2)}%`;
}
var It = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 }
		};
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
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
		let t = Mt(e), n = Nt(e, t.circuits), { paths: r } = t, i = t.circuits.length, a = i ? `minmax(0, 44fr) repeat(${i}, minmax(0, ${(54 / i).toFixed(2)}fr)) minmax(0, 2fr)` : "1fr", o = n.flat().filter((e) => e.calling).map((e) => e.name), s = t.labels[1]?.text ?? "", c = `${X.x} ${X.y} ${X.width} ${X.height}`;
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
                style="left: ${Q(135, X.x, X.width)}; top: ${Q(205, X.y, X.height)}"
              >
                <path d=${Ft}></path>
              </svg>
              ${t.labels.map((e) => A`<span
                  class=${e.kind}
                  style="left: ${Q(e.x, X.x, X.width)}; top: ${Q(e.y, X.y, X.height)}"
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
customElements.get("vtherm-smart-boiler-schematic") || customElements.define(Pt, It);
// src/timeline-card.ts
var Lt = "vtherm-smart-boiler-timeline", Rt = 1e3, zt = 170, $ = 720, Bt = 100, Vt = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			history: { attribute: !1 },
			from: { type: Number },
			to: { type: Number },
			at: { attribute: !1 },
			status: { attribute: !1 },
			playing: { state: !0 },
			speed: { state: !0 }
		};
	}
	constructor() {
		super(), this.history = null, this.from = 0, this.to = 0, this.at = null, this.status = "loading", this.playing = !1, this.speed = 1;
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this.stop();
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	get language() {
		return this.hass?.locale?.language ?? this.hass?.language ?? "en";
	}
	emit(e) {
		this.dispatchEvent(new CustomEvent("at-change", {
			detail: e,
			bubbles: !0,
			composed: !0
		}));
	}
	stepOf(e) {
		return e == null || this.to <= this.from ? $ : Math.round((e - this.from) / (this.to - this.from) * $);
	}
	timeOf(e) {
		return e >= $ ? null : this.from + (this.to - this.from) * e / $;
	}
	stop() {
		this.timer !== void 0 && window.clearInterval(this.timer), this.timer = void 0, this.playing = !1;
	}
	togglePlay() {
		if (this.playing) {
			this.stop();
			return;
		}
		let e = this.at == null ? 0 : this.stepOf(this.at);
		this.playing = !0, this.emit(this.timeOf(e)), this.timer = window.setInterval(() => {
			e += this.speed, e >= $ ? (this.stop(), this.emit(null)) : this.emit(this.timeOf(e));
		}, Bt);
	}
	render() {
		if (!this.installation || !this.hass) return M;
		let e = this.language, t = this.status === "loading" ? A`<p class="muted">${this.t("timeline.loading")}</p>` : this.status === "ready" ? this.chart(e) : A`<p class="error" role="alert">${this.t("timeline.error", { message: this.status })}</p>`;
		return A`<section class="card">
      <div class="head">
        <div>
          <h3>${this.t("timeline.title")}</h3>
          <div class="muted small">${this.t("timeline.hint")}</div>
        </div>
        <div class="controls">
          <span class="time">${this.at == null ? "" : G(this.at, e)}</span>
          <button
            class="play"
            aria-label=${this.playing ? this.t("timeline.pause") : this.t("timeline.play")}
            ?disabled=${this.status !== "ready"}
            @click=${() => this.togglePlay()}
          >
            ${this.playing ? A`<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>` : A`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"></path></svg>`}
          </button>
          ${[1, 4].map((e) => A`<button
              class="pill ${this.speed === e ? "on" : ""}"
              aria-pressed=${this.speed === e ? "true" : "false"}
              @click=${() => this.speed = e}
            >
              ×${e}
            </button>`)}
          <button
            class="pill"
            @click=${() => {
			this.stop(), this.emit(null);
		}}
          >
            ${this.t("timeline.now")}
          </button>
        </div>
      </div>
      ${t}
    </section>`;
	}
	chart(e) {
		let t = this.installation, n = this.history ?? {}, { from: r, to: i } = this, a = (e) => n[t.signals[e] ?? ""], o = (e) => n[t.entities[e] ?? ""], s = o("control_setpoint") ? $e(o("control_setpoint"), "requested") : $e(o("control_state"), "target"), c = $e(a("flow")), l = $e(a("return"));
		if (!W(s) && !W(c) && !W(l) && !a("flame")) return A`<p class="muted">${this.t("timeline.no_history")}</p>`;
		let [u, d] = rt([
			s,
			c,
			l
		]), f = (e) => nt(e, r, i, u, d, Rt, zt), p = (e) => `${((e - r) / (i - r) * 100).toFixed(3)}%`, m = (e, t) => `${Math.max(.25, (t - e) / (i - r) * 100).toFixed(3)}%`, h = a("dhw_active"), g = tt(a("flame"), r, i, (e) => e === "on"), _ = tt(h, r, i, (e) => e === "on"), v = [];
		for (let e = u; e <= d; e += 10) v.push(`M0 ${((d - e) / (d - u) * zt).toFixed(1)}H${Rt}`);
		let y = p(this.at ?? i), b = this.at ?? i, x = (e) => et(e, b);
		return A`
      <div class="legend">
        ${W(s) ? A`<span><i class="line dash"></i>${this.t("timeline.legend_requested")} ${V(x(s), e)}</span>` : M}
        ${W(c) ? A`<span><i class="line flow"></i>${this.t("timeline.legend_flow")} ${V(x(c), e)}</span>` : M}
        ${W(l) ? A`<span><i class="line ret"></i>${this.t("timeline.legend_return")} ${V(x(l), e)}</span>` : M}
        ${g.length ? A`<span><i class="box heat"></i>${this.t("timeline.legend_heat")}</span>` : M}
        ${_.length ? A`<span><i class="box hot"></i>${this.t("timeline.legend_hot_water")}</span>` : M}
      </div>
      <div class="chart">
        <div class="yaxis" aria-hidden="true">
          ${Array.from({ length: (d - u) / 10 + 1 }, (e, t) => u + t * 10).map((e) => A`<span style="top: ${((d - e) / (d - u) * 100).toFixed(2)}%">${e}</span>`)}
        </div>
        <div class="plot-wrap">
          <div class="plot" role="img" aria-label=${this.t("timeline.title")}>
            <svg viewBox="0 0 ${Rt} ${zt}" preserveAspectRatio="none" aria-hidden="true">
              ${ge`
                <path class="grid" d=${v.join("")}></path>
                <path class="ret" d=${f(l)}></path>
                <path class="flow" d=${f(c)}></path>
                <path class="requested" d=${f(s)}></path>
              `}
            </svg>
            <span class="cursor" style="left: ${y}"></span>
          </div>
          <div class="strip">
            ${g.map(([e, t]) => A`<span class="burn heat" style="left: ${p(e)}; width: ${m(e, t)}"></span>`)}
            ${_.map(([e, t]) => A`<span class="burn hot" style="left: ${p(e)}; width: ${m(e, t)}"></span>`)}
            <span class="cursor" style="left: ${y}"></span>
          </div>
          <input
            class="scrub"
            type="range"
            min="0"
            max=${$}
            step="1"
            .value=${String(this.stepOf(this.at))}
            aria-label=${this.t("timeline.slider")}
            aria-valuetext=${this.at == null ? this.t("timeline.now") : G(this.at, e)}
            @input=${(e) => {
			this.stop(), this.emit(this.timeOf(Number(e.target.value)));
		}}
          />
          <div class="xaxis" aria-hidden="true">
            ${it(r, i, this.offsetWidth < 560 ? 8 : 4, e).map((e) => A`<span style="left: ${p(e.t)}">${e.label}</span>`)}
          </div>
        </div>
      </div>
    `;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      --sb-requested: #2a78d6;
      --sb-flow: #eb6834;
      --sb-return: #1baf7a;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px 16px;
      margin-bottom: 10px;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .error {
      color: var(--error-color, #db4437);
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .time {
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      min-width: 48px;
      text-align: right;
    }
    .play {
      appearance: none;
      border: 0;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .play:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .play svg {
      width: 20px;
      height: 20px;
      fill: currentColor;
    }
    .pill {
      appearance: none;
      border: 0;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      min-height: 36px;
      padding: 0 12px;
      border-radius: 999px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .pill.on {
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-bottom: 8px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .line {
      display: inline-block;
      width: 14px;
      border-top: 2px solid;
    }
    .line.dash {
      border-top-style: dashed;
      border-color: var(--sb-requested);
    }
    .line.flow {
      border-color: var(--sb-flow);
    }
    .line.ret {
      border-color: var(--sb-return);
    }
    .box {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .box.heat,
    .burn.heat {
      background: var(--sb-requested);
    }
    .box.hot,
    .burn.hot {
      background: var(--sb-flow);
    }
    .chart {
      display: flex;
      gap: 8px;
    }
    .yaxis {
      position: relative;
      width: 26px;
      flex: none;
      height: 170px;
    }
    .yaxis span {
      position: absolute;
      right: 0;
      transform: translateY(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .plot-wrap {
      flex: 1;
      min-width: 0;
    }
    .plot {
      position: relative;
      height: 170px;
    }
    .plot svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }
    .grid,
    .requested,
    .flow,
    .ret {
      fill: none;
      vector-effect: non-scaling-stroke;
      stroke-linejoin: round;
    }
    .grid {
      stroke: var(--divider-color, rgba(0, 0, 0, 0.12));
      stroke-width: 1px;
    }
    .requested {
      stroke: var(--sb-requested);
      stroke-width: 2px;
      stroke-dasharray: 6 4;
    }
    .flow {
      stroke: var(--sb-flow);
      stroke-width: 2px;
    }
    .ret {
      stroke: var(--sb-return);
      stroke-width: 2px;
    }
    .strip {
      position: relative;
      height: 26px;
      margin-top: 8px;
      border-radius: 6px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .burn {
      position: absolute;
      top: 5px;
      bottom: 5px;
      border-radius: 3px;
      min-width: 2px;
    }
    .cursor {
      position: absolute;
      top: -4px;
      bottom: -4px;
      width: 2px;
      margin-left: -1px;
      background: var(--primary-text-color);
      border-radius: 1px;
      pointer-events: none;
    }
    .scrub {
      width: 100%;
      margin: 0;
      height: 28px;
      accent-color: var(--primary-color);
      cursor: pointer;
    }
    .xaxis {
      position: relative;
      height: 16px;
    }
    .xaxis span {
      position: absolute;
      transform: translateX(-50%);
      font-size: 11px;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-timeline") || customElements.define(Lt, Vt);
// src/overview.ts
var Ht = "vtherm-smart-boiler-overview", Ut = "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z", Wt = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			confirming: { state: !0 },
			error: { state: !0 },
			history: { state: !0 },
			historyStatus: { state: !0 },
			at: { state: !0 }
		};
	}
	constructor() {
		super(), this.window = [0, 0], this.historyAsked = !1, this.confirming = !1, this.error = "", this.history = null, this.historyStatus = "loading", this.at = null;
	}
	willUpdate() {
		this.hass && this.installation && !this.historyAsked && (this.historyAsked = !0, this.askHistory());
	}
	async askHistory() {
		let e = this.hass, t = Date.now(), n = t - Je;
		this.window = [n, t];
		try {
			let r = await e.callWS({
				type: "history/history_during_period",
				start_time: new Date(n).toISOString(),
				end_time: new Date(t).toISOString(),
				entity_ids: Ye(this.installation),
				include_start_time_state: !0,
				significant_changes_only: !1,
				minimal_response: !1,
				no_attributes: !1
			});
			this.history = Xe(r), this.historyStatus = "ready";
		} catch (e) {
			let t = e?.message;
			this.historyStatus = typeof t == "string" ? t : String(e);
		}
	}
	shown() {
		let e = this.hass;
		return !e || this.at == null || !this.history ? e : {
			...e,
			states: Qe(this.history, this.at, e.states)
		};
	}
	moveTo(e) {
		this.at = e, e == null && Date.now() - this.window[1] > 3e5 && this.askHistory();
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	view() {
		let e = this.shown();
		return !e || !this.installation ? null : Ke({
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
		let { status: t, control: n, tiles: r } = e, i = this.at != null, a = n !== null && n.available && this.isAdmin && !i, o = this.shown(), s = n ? i ? this.t("control.replay_hint") : n.available ? this.isAdmin ? n.on ? this.t("control.hint_on") : this.t("control.hint_off") : this.t("control.admin_only") : this.t("control.unavailable") : "";
		return A`
      <section class="card hero">
        <div class="status">
          <div class="flame ${t.flame ? "lit" : ""}" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d=${Ut}></path></svg>
          </div>
          <div class="words">
            <div class="title-row">
              <h2>${t.title}</h2>
              ${i ? A`<span class="chip">${this.t("control.replay", { time: G(this.at, this.hass?.locale?.language ?? this.hass?.language ?? "en") })}</span>` : M}
            </div>
            ${t.detail ? A`<p>${t.detail}</p>` : M}
          </div>
        </div>
        ${n ? A`<div class="control">
              <div class="label">
                <div>${this.t("control.label")} <span class="muted">${this.t("control.experimental")}</span></div>
                <div class="muted small">${s}</div>
              </div>
              <button
                class="switch ${n.on ? "on" : ""}"
                role="switch"
                aria-checked=${n.on ? "true" : "false"}
                aria-label=${this.t("control.label")}
                ?disabled=${!a}
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

      <div class="row">
        <vtherm-smart-boiler-schematic
          class="wide"
          .hass=${o}
          .installation=${this.installation}
        ></vtherm-smart-boiler-schematic>
        <vtherm-smart-boiler-curve
          class="side"
          .hass=${o}
          .installation=${this.installation}
        ></vtherm-smart-boiler-curve>
      </div>

      <vtherm-smart-boiler-timeline
        .hass=${this.hass}
        .installation=${this.installation}
        .history=${this.history}
        .from=${this.window[0]}
        .to=${this.window[1]}
        .at=${this.at}
        .status=${this.historyStatus}
        @at-change=${(e) => this.moveTo(e.detail)}
      ></vtherm-smart-boiler-timeline>

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
    .title-row {
      display: flex;
      align-items: baseline;
      gap: 10px;
      flex-wrap: wrap;
    }
    .chip {
      font-size: 12px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 999px;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
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
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: flex-start;
    }
    .wide {
      flex: 999 1 640px;
      min-width: 0;
    }
    .side {
      flex: 1 1 360px;
      min-width: 0;
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
customElements.get("vtherm-smart-boiler-overview") || customElements.define(Ht, Wt);
// src/use.ts
var Gt = [
	"weather",
	"dhw",
	"settings",
	"other"
];
function Kt(e) {
	let t = e.contributions ?? {}, n = Array.isArray(e.not_judged) ? e.not_judged : [], r = Gt.map((e) => {
		let n = t[e];
		return typeof n == "number" && Number.isFinite(n) ? n : null;
	}), i = Math.max(0, ...r.map((e) => Math.abs(e ?? 0)));
	return Gt.map((t, a) => {
		let o = r[a];
		return {
			cause: t,
			amount: o,
			width: o == null || i === 0 ? 0 : Math.abs(o) / i * 100,
			more: (o ?? 0) > 0,
			normal: t === "other" && e.other_within_normal === !0,
			judged: !n.includes(t)
		};
	});
}
function qt(e) {
	let t = Math.max(0, ...e.map((e) => e.per_degree_day ?? 0));
	if (t <= 0) return 1;
	let n = t > 5 ? 2 : t > 1 ? 1 : .2;
	return Math.ceil(t * 1.1 / n) * n;
}
// src/use-view.ts
var Jt = "vtherm-smart-boiler-use";
function Yt(e) {
	return Math.abs(e) < 1 ? 2 : 1;
}
var Xt = 18e5, Zt = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			weeks: { state: !0 },
			error: { state: !0 },
			hovered: { state: !0 }
		};
	}
	constructor() {
		super(), this.weeks = null, this.error = "", this.hovered = "";
	}
	connectedCallback() {
		super.connectedCallback(), this.timer = window.setInterval(() => void this.fetchWeeks(), Xt);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), window.clearInterval(this.timer);
	}
	firstUpdated() {
		this.fetchWeeks();
	}
	async fetchWeeks() {
		if (this.hass) try {
			let e = await this.hass.callWS({
				type: "vtherm_smart_boiler/days",
				since: Date.now() / 1e3
			});
			this.weeks = e.weeks, this.error = "";
		} catch (e) {
			let t = e?.message;
			this.error = this.t("use.error", { message: typeof t == "string" ? t : String(e) });
		}
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	get language() {
		return this.hass?.locale?.language ?? this.hass?.language ?? "en";
	}
	entity(e) {
		return this.hass?.states[this.installation?.entities[e] ?? ""];
	}
	date(e) {
		try {
			return new Intl.DateTimeFormat(this.language, {
				day: "numeric",
				month: "short"
			}).format(e * 1e3);
		} catch {
			return (/* @__PURE__ */ new Date(e * 1e3)).toISOString().slice(0, 10);
		}
	}
	render() {
		if (!this.hass || !this.installation) return M;
		let e = this.language, t = (t, n) => {
			let r = this.entity(t);
			if (!r) return M;
			let i = z(r.state), a = r.attributes.unit_of_measurement;
			return A`<div class="card tile">
        <div class="tile-label">${this.t(`use.${t}`)}</div>
        <div class="tile-value">${i == null ? "—" : B(i, e, n)}${i != null && typeof a == "string" ? A` <span class="unit">${a}</span>` : M}</div>
        <div class="muted small">${this.t(`use.${t}_detail`)}</div>
      </div>`;
		}, n = this.entity("gas_per_degree_day"), r = typeof n?.attributes.unit_of_measurement == "string" ? n.attributes.unit_of_measurement : "", i = this.weeks ?? [], a = qt(i), o = this.entity("change_report"), s = o?.attributes ?? {}, c = Kt(s), l = typeof s.previous == "number" ? s.previous : null, u = typeof s.current == "number" ? s.current : null, d = typeof s.unit == "string" ? s.unit : "", f = z(o?.state);
		return A`
      <section class="tiles">${t("gas_per_degree_day", 2)}${t("degree_days", 0)}</section>
      <div class="row">
        <section class="card wide">
          <h3>${this.t("use.weeks")}</h3>
          <p class="muted small">${this.t("use.weeks_hint")}</p>
          ${this.error ? A`<p class="error" role="alert">${this.error}</p>` : i.length ? A`
                  <div class="bars" role="img" aria-label=${i.map((e) => this.weekText(e, r)).join("; ")}>
                    ${i.map((t, n) => {
			let o = t.per_degree_day, s = o == null ? 0 : o / a * 100;
			return A`<div
                        class="bar-cell"
                        @mouseenter=${() => this.hovered = this.weekText(t, r)}
                        @mouseleave=${() => this.hovered = ""}
                      >
                        ${n === i.length - 1 && o != null ? A`<span class="bar-count">${B(o, e, 2)}</span>` : M}
                        <span class="bar ${n === i.length - 1 ? "now" : ""} ${o == null ? "none" : ""}" style="height: ${o == null ? 100 : s.toFixed(1)}%"></span>
                      </div>`;
		})}
                  </div>
                  <div class="bar-labels" aria-hidden="true">
                    ${i.map((e, t) => A`<span>${t % 2 == i.length % 2 || t === i.length - 1 ? this.date(e.start) : ""}</span>`)}
                  </div>
                  <p class="muted small hover" aria-live="polite">${this.hovered || r}</p>
                ` : A`<p class="muted">${this.t("use.weeks_none")}</p>`}
        </section>
        <section class="card side">
          <h3>${this.t("use.change")}</h3>
          ${!o || l == null || u == null ? A`<p class="muted">${this.t("use.no_report")}</p>` : A`
                <p class="big">
                  ${this.t("use.total", {
			sign: u - l > 0 ? "+" : u - l < 0 ? "−" : "±",
			value: B(Math.abs(u - l), e, Yt(u - l)),
			unit: d,
			percent: f == null ? "—" : `${f > 0 ? "+" : ""}${B(f, e, 0)} %`
		})}
                </p>
                <p class="muted small">${this.t("use.change_hint")}</p>
                <div class="sides muted small"><span>← ${this.t("use.less")}</span><span>${this.t("use.more")} →</span></div>
                ${c.map((t) => A`<div class="cause">
                    <div class="cause-head">
                      <span>${this.t(`use.${t.cause}`)}
                        ${t.normal ? A`<span class="muted small"> · ${this.t("use.normal")}</span>` : M}
                        ${t.judged ? M : A`<span class="muted small"> · ${this.t("use.not_judged")}</span>`}</span>
                      <b>${t.amount == null ? "—" : `${t.amount > 0 ? "+" : t.amount < 0 ? "−" : "±"}${B(Math.abs(t.amount), e, Yt(t.amount))} ${d}`}</b>
                    </div>
                    <div class="track">
                      <span class="zero"></span>
                      <span class="fill ${t.more ? "more" : "less"}" style="width: ${(t.width / 2).toFixed(1)}%"></span>
                    </div>
                  </div>`)}
                <div class="legend">
                  <span><i class="more"></i>${this.t("use.more")}</span>
                  <span><i class="less"></i>${this.t("use.less")}</span>
                </div>
              `}
        </section>
      </div>
    `;
	}
	weekText(e, t) {
		let n = this.date(e.start);
		return e.per_degree_day == null ? this.t("use.week_none", { date: n }) : this.t("use.week", {
			date: n,
			value: `${B(e.per_degree_day, this.language, 2)} ${t}`.trim()
		});
	}
	static {
		this.styles = o`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
      --sb-bar: #2a78d6;
      --sb-more: #e34948;
      --sb-less: #2a78d6;
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
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
    .unit {
      font-size: 15px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: flex-start;
    }
    .wide {
      flex: 999 1 560px;
    }
    .side {
      flex: 1 1 340px;
    }
    h3 {
      margin: 0 0 4px;
      font-size: 16px;
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .error {
      color: var(--error-color, #db4437);
    }
    .bars {
      height: 200px;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 6px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.2));
      margin-top: 14px;
    }
    .bar-cell {
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
    }
    .bar {
      display: block;
      border-radius: 4px 4px 0 0;
      background: var(--sb-bar);
      opacity: 0.55;
    }
    .bar.now {
      opacity: 1;
    }
    .bar.none {
      opacity: 1;
      background: repeating-linear-gradient(
        135deg,
        transparent 0 4px,
        var(--divider-color, rgba(0, 0, 0, 0.12)) 4px 6px
      );
    }
    .bar-cell:hover .bar {
      outline: 2px solid var(--primary-text-color);
      outline-offset: 1px;
    }
    .bar-count {
      text-align: center;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 2px;
    }
    .bar-labels {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(0, 1fr);
      gap: 6px;
      font-size: 11px;
      color: var(--secondary-text-color);
      text-align: center;
      margin-top: 6px;
      white-space: nowrap;
    }
    .hover {
      min-height: 16px;
      margin: 8px 0 0;
    }
    .big {
      font-size: 20px;
      font-weight: 700;
      margin: 6px 0 2px;
      font-variant-numeric: tabular-nums;
    }
    .sides {
      display: flex;
      justify-content: space-between;
      margin: 10px 0 6px;
    }
    .cause {
      margin-bottom: 12px;
    }
    .cause-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      margin-bottom: 4px;
    }
    .cause-head b {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .track {
      position: relative;
      height: 18px;
      border-radius: 4px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    .zero {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 50%;
      width: 1px;
      background: var(--divider-color, rgba(0, 0, 0, 0.3));
    }
    .fill {
      position: absolute;
      top: 4px;
      bottom: 4px;
    }
    .fill.more {
      left: 50%;
      border-radius: 0 4px 4px 0;
      background: var(--sb-more);
    }
    .fill.less {
      right: 50%;
      border-radius: 4px 0 0 4px;
      background: var(--sb-less);
    }
    .legend {
      display: flex;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend i {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
    }
    .legend .more {
      background: var(--sb-more);
    }
    .legend .less {
      background: var(--sb-less);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-use") || customElements.define(Jt, Zt);
// src/panel.ts
var Qt = "vtherm-smart-boiler-panel", $t = [
	"overview",
	"burner",
	"use"
];
function en(e) {
	let t = e.replace(/^#/, "");
	return $t.includes(t) ? t : "overview";
}
var tn = class extends I {
	static {
		this.properties = {
			hass: { attribute: !1 },
			narrow: { type: Boolean },
			panel: { attribute: !1 },
			load: { state: !0 },
			tab: { state: !0 }
		};
	}
	constructor() {
		super(), this.requested = !1, this.narrow = !1, this.load = { kind: "loading" }, this.tab = en(location.hash);
	}
	choose(e) {
		this.tab = e, history.replaceState(history.state, "", e === "overview" ? location.pathname : `#${e}`);
	}
	t(e, t) {
		return R(this.hass?.language, e, t);
	}
	willUpdate() {
		this.hass && !this.requested && (this.requested = !0, this.fetchInstallation());
	}
	async fetchInstallation(e = !0) {
		if (this.hass) {
			e && (this.load = { kind: "loading" });
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
	refetchSoon() {
		window.setTimeout(() => void this.fetchInstallation(!1), 3e3);
	}
	body() {
		switch (this.load.kind) {
			case "loading": return A`<p class="note">${this.t("panel.loading")}</p>`;
			case "not_running": return A`<p class="note">${this.t("panel.not_running")}</p>`;
			case "error": return A`<p class="note error" role="alert">
          ${this.t("panel.error", { message: this.load.message })}
        </p>`;
			case "ready": return A`<vtherm-smart-boiler-overview
            ?hidden=${this.tab !== "overview"}
            .hass=${this.hass}
            .installation=${this.load.installation}
            @installation-changed=${() => this.refetchSoon()}
          ></vtherm-smart-boiler-overview>
          <vtherm-smart-boiler-burner
            ?hidden=${this.tab !== "burner"}
            .hass=${this.hass}
            .installation=${this.load.installation}
          ></vtherm-smart-boiler-burner>
          <vtherm-smart-boiler-use
            ?hidden=${this.tab !== "use"}
            .hass=${this.hass}
            .installation=${this.load.installation}
          ></vtherm-smart-boiler-use>`;
		}
	}
	render() {
		return A`
      <header class="toolbar">
        ${this.narrow ? A`<ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>` : M}
        <h1>${this.t("panel.title")}</h1>
      </header>
      <nav class="tabs" aria-label=${this.t("tabs.label")}>
        ${$t.map((e) => A`<button
            class="tab ${this.tab === e ? "on" : ""}"
            aria-current=${this.tab === e ? "page" : "false"}
            @click=${() => this.choose(e)}
          >
            ${this.t(`tabs.${e}`)}
          </button>`)}
      </nav>
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
    .tabs {
      display: flex;
      gap: 2px;
      padding: 0 8px;
      overflow-x: auto;
      background: var(--app-header-background-color, var(--primary-color));
    }
    .tab {
      appearance: none;
      border: 0;
      background: none;
      font: inherit;
      font-weight: 500;
      padding: 0 16px;
      height: 44px;
      color: var(--app-header-text-color, var(--text-primary-color));
      opacity: 0.75;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      white-space: nowrap;
    }
    .tab.on {
      opacity: 1;
      border-bottom-color: var(--app-header-text-color, var(--text-primary-color));
    }
    .tab:focus-visible {
      outline: 2px solid var(--app-header-text-color, #fff);
      outline-offset: -4px;
    }
    [hidden] {
      display: none !important;
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
customElements.get("vtherm-smart-boiler-panel") || customElements.define(Qt, tn);
export { Qt as PANEL_TAG, tn as SmartBoilerPanel };
